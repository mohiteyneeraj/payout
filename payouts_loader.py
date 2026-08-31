"""Google Sheets loader for the Interviewer Payouts tool.

Parses every monthly tab of the "Interview PAYOUT <> CALC" sheet, builds an
interviewer directory (email/phone -> identity) from each tab's roster block,
and aggregates per-interview payout rows into monthly totals + detail lists
per interviewer.
"""
import os
import re
import time
import datetime
import threading
from dateutil import parser as _dateutil_parser

_DATETIME_MIN = datetime.datetime.min

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Interview-date strings mix m/d/yyyy and d-m-yyyy formats across eras;
# dateutil resolves the ambiguity (day-first fallback) well enough for
# display sort order -- this is never used for payout math.
def _parse_date(v):
    s = str(v or '').strip()
    if not s:
        return None
    try:
        return _dateutil_parser.parse(s)
    except (ValueError, OverflowError):
        return None

SA_FILE   = os.environ.get('SA_FILE_PATH') or os.path.join(os.path.dirname(__file__), 'service_account.json')
SCOPES    = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SHEET_ID  = '1LW1hkXNz1LAvqB9EOV52lWRu36VoSw8uabRWsaVS78g'
LAST_COL  = 'AN'   # generous upper bound; widest known tab is 34 cols (AH)

# Tabs that look like monthly payout data but aren't (legacy/unrelated) —
# confirmed by direct inspection of their contents.
EXCLUDE_TABS = {
    'Sheet25', 'Sheet19', 'Feb Db',
    "Jan' 26' Payouts ( Calling Data)",
    'For panelists', 'PAYOUT CONS',
    'CONS <> CALC INTL', 'CONS <> CALC INDO',
    'Document links for payout sheet',
}

# Tabs that hold *extra* rows for a month whose main data lives in another
# tab — merge these into the target instead of treating as their own month.
MERGE_INTO = {
    'June Payouts- Manasa': 'June Payouts',
}

_MONTH_ABBR = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}
_MONTH_LABEL = {
    1: 'January', 2: 'February', 3: 'March', 4: 'April', 5: 'May', 6: 'June',
    7: 'July', 8: 'August', 9: 'September', 10: 'October', 11: 'November', 12: 'December',
}

_cache: dict = {'df': None, 'directory': None, 'months': None, 'ts': 0.0,
                'warnings': [], 'tab_count': 0}
_load_lock   = threading.Lock()
_loading_now = False
CACHE_TTL    = 1800  # 30 minutes

# Older tabs are skipped entirely (not even fetched) to bound memory --
# the full history back to 2024 doesn't fit in a 512MB instance alongside
# the Sheets/Flask baseline. 'YYYY-MM': first month to load, inclusive.
_MIN_MONTH = os.environ.get('MIN_PAYOUT_MONTH', '2026-04')
MIN_MONTH_KEY = tuple(int(p) for p in _MIN_MONTH.split('-'))


# ── Google Sheets helpers ───────────────────────────────────────────────────

def _build_service(http_timeout: int = 120):
    import httplib2
    import google_auth_httplib2
    creds = service_account.Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    http  = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=http_timeout))
    return build('sheets', 'v4', http=http)


def _list_tabs(service) -> list:
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    return [s['properties']['title'] for s in meta.get('sheets', [])]


def _fetch_tab(service, tab: str, retries: int = 3) -> list:
    """Return the raw values grid (list of lists) for a tab."""
    last_exc = None
    for attempt in range(retries):
        if attempt:
            time.sleep(3 * attempt)
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SHEET_ID,
                range=f"'{tab}'!A1:{LAST_COL}",
                valueRenderOption='FORMATTED_VALUE',
            ).execute()
            return res.get('values', [])
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if any(k in err for k in ('503', 'unavailable', 'timed out', 'timeout',
                                       'connection reset', 'remotedisconnected')):
                continue
            raise
    raise last_exc


# ── Tab classification ──────────────────────────────────────────────────────

def _month_key(tab: str):
    """Return (year, month_num) for a canonical '<Month> Payouts' tab, or None."""
    first = tab.strip().split()[0].strip("'")
    abbr = first[:3].lower()
    month_num = _MONTH_ABBR.get(abbr)
    if not month_num:
        return None
    year_match = re.search(r"\b(\d{2})'", tab)
    year = 2000 + int(year_match.group(1)) if year_match else 2024
    return (year, month_num)


def _classify_tabs(all_tabs: list) -> dict:
    """Return {month_key: [tab, ...]} — tabs to merge together per month."""
    months: dict = {}
    for tab in all_tabs:
        if tab in EXCLUDE_TABS:
            continue
        target = MERGE_INTO.get(tab, tab)
        if target != tab and target not in all_tabs:
            continue
        if not tab.strip().endswith('Payouts') and tab not in MERGE_INTO:
            continue
        key = _month_key(target)
        if key is None or key < MIN_MONTH_KEY:
            continue
        months.setdefault(key, [])
        if tab not in months[key]:
            months[key].append(tab)
    return months


# ── Header-driven column lookup (positions drift across eras) ──────────────

def _norm_header(h) -> str:
    return re.sub(r'\s+', ' ', str(h).strip().lower())


def _find_col(headers: list, *, equals=None, contains_all=None) -> int:
    for i, h in enumerate(headers):
        nh = _norm_header(h)
        if equals is not None and nh == equals:
            return i
        if contains_all is not None and all(c in nh for c in contains_all):
            return i
    return -1


def _find_header_cell(grid: list, *, equals=None, contains_all=None, max_scan: int = 3):
    """Some blocks (e.g. the roster table) have their header row shifted down
    by a row or two relative to the sheet's main header. Scan the first few
    rows and return (row_idx, col_idx) of the first match, or (-1, -1)."""
    for ri in range(min(max_scan, len(grid))):
        idx = _find_col(grid[ri], equals=equals, contains_all=contains_all)
        if idx >= 0:
            return ri, idx
    return -1, -1


def _num(v) -> float:
    s = str(v).replace(',', '').strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _norm_name(v) -> str:
    return re.sub(r'\s+', ' ', str(v).strip()).casefold()


_JUNK_NAMES = {'total', 'grand total', 'sub total', 'subtotal', ''}


def _is_junk_name(v) -> bool:
    n = _norm_name(v)
    return n in _JUNK_NAMES or n.replace('.', '').isdigit()


def _looks_like_name(v) -> bool:
    """Roster 'name' cells occasionally hold a phone number instead of a name
    (see roster column-order handling below) — never treat those as identity."""
    n = str(v).strip()
    return bool(n) and bool(re.search(r'[a-zA-Z]', n))


def _norm_email(v) -> str:
    return str(v).strip().lower()


# Recent tabs (Apr 2026 onward) repurpose the 'Subject' column to also carry
# the interview's attendance outcome, e.g. 'Math No Show' / 'Math - Reschedule'
# alongside the plain subject name ('Math') for a completed interview. Older
# tabs use that column purely as a subject name with no such suffix, so an
# unrecognized/blank value defaults to 'done' rather than 'unknown'.
def _classify_attendance(subject_raw) -> str:
    s = str(subject_raw or '').strip().lower()
    if 'no show' in s or 'reschedul' in s:
        return 'no_show'
    return 'done'


ATTENDANCE_LABELS = {
    'done': 'Interview Done',
    'no_show': 'Reschedule/No Show/NI',
}


# ── Per-tab parsing ──────────────────────────────────────────────────────────

def _parse_tab(grid: list, month_label: str):
    """Returns (raw_records, roster_rows, rollup_rows) for one tab's grid."""
    if not grid:
        return [], [], []
    headers = grid[0]
    rows    = grid[1:]

    col_cand   = _find_col(headers, equals="candidate's name")
    if col_cand < 0:
        col_cand = _find_col(headers, equals='name')
    col_phone  = _find_col(headers, contains_all=['phone'])
    col_date   = _find_col(headers, contains_all=['interview', 'date'])
    col_subject     = _find_col(headers, equals='subject')
    col_interviewer = _find_col(headers, equals='interviewer')
    col_reviewer    = _find_col(headers, equals='reviewer')
    col_pay_int = _find_col(headers, contains_all=['payout', 'interviewer'])
    col_pay_rev = _find_col(headers, contains_all=['payout', 'reviewer'])

    raw_records = []
    if col_interviewer >= 0 or col_reviewer >= 0:
        for r in rows:
            def cell(i):
                return r[i] if 0 <= i < len(r) else ''
            candidate = str(cell(col_cand)).strip()
            date_raw  = cell(col_date)
            attendance = _classify_attendance(cell(col_subject)) if col_subject >= 0 else 'done'
            if col_interviewer >= 0:
                person = str(cell(col_interviewer)).strip()
                amount = _num(cell(col_pay_int)) if col_pay_int >= 0 else 0.0
                if person and amount and not _is_junk_name(person):
                    raw_records.append({
                        'person': person, 'role': 'Interviewer', 'candidate': candidate,
                        'date_raw': date_raw, 'amount': amount, 'month': month_label,
                        'attendance': attendance,
                    })
            if col_reviewer >= 0:
                person = str(cell(col_reviewer)).strip()
                amount = _num(cell(col_pay_rev)) if col_pay_rev >= 0 else 0.0
                if person and amount and not _is_junk_name(person):
                    raw_records.append({
                        'person': person, 'role': 'Reviewer', 'candidate': candidate,
                        'date_raw': date_raw, 'amount': amount, 'month': month_label,
                        'attendance': attendance,
                    })

    # ── Rollup block: Name | Count of interviews | Amount ──────────────────
    rollup_rows = []
    row_count, col_count = _find_header_cell(grid, equals='count of interviews')
    if col_count >= 0 and col_count > 0:
        col_name_r = col_count - 1
        col_amount_r = col_count + 1
        for r in grid[row_count + 1:]:
            def cell(i):
                return r[i] if 0 <= i < len(r) else ''
            name = str(cell(col_name_r)).strip()
            if name:
                rollup_rows.append({'name': name, 'count': _num(cell(col_count)),
                                     'amount': _num(cell(col_amount_r))})

    # ── Roster block: DB ID | Interviewer | Number | Email | ... ───────────
    # Column order after "DB ID" drifts across tab eras (some are
    # DB ID | Interviewer | Number | Email, others DB ID | Number | Email |
    # Interviewer) — look each one up by its own header label instead of
    # assuming a fixed offset, so a mismatched era doesn't file a name cell
    # under phone/email or vice versa.
    roster_rows = []
    row_dbid, col_dbid = _find_header_cell(grid, equals='db id')
    if col_dbid >= 0:
        header_row = grid[row_dbid] if row_dbid < len(grid) else []
        sub = header_row[col_dbid + 1:]

        def _sub_col(**kwargs):
            idx = _find_col(sub, **kwargs)
            return col_dbid + 1 + idx if idx >= 0 else -1

        col_name_p  = _sub_col(equals='interviewer')
        if col_name_p < 0:
            col_name_p = _sub_col(equals='name')
        col_phone_p = _sub_col(contains_all=['number'])
        if col_phone_p < 0:
            col_phone_p = _sub_col(contains_all=['phone'])
        col_email_p = _sub_col(contains_all=['email'])

        # Historical fixed layout, only as a fallback for tabs whose header
        # cells didn't match any of the labels above.
        if col_name_p < 0:
            col_name_p = col_dbid + 1
        if col_phone_p < 0:
            col_phone_p = col_dbid + 2
        if col_email_p < 0:
            col_email_p = col_dbid + 3
        for r in grid[row_dbid + 1:]:
            def cell(i):
                return r[i] if 0 <= i < len(r) else ''
            dbid = str(cell(col_dbid)).strip()
            name = str(cell(col_name_p)).strip()
            if dbid and name and dbid.lower() != 'db id':
                roster_rows.append({
                    'db_id': dbid, 'name': name,
                    'phone': str(cell(col_phone_p)).strip(),
                    'email': str(cell(col_email_p)).strip(),
                })

    return raw_records, roster_rows, rollup_rows


# ── Identity merge ───────────────────────────────────────────────────────────
# The same interviewer sometimes gets a different DB ID across tabs/eras
# (re-registration, sheet typo, etc.) and shows up as duplicate rows with the
# same display name. Merge directory entries that share an email or phone —
# those are a much stronger identity signal than name text.

def _merge_directory_by_contact(directory: dict, name_to_dbids: dict):
    parent = {dbid: dbid for dbid in directory}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_email: dict = {}
    by_phone: dict = {}
    for dbid, entry in directory.items():
        for e in entry['emails']:
            if e in by_email:
                union(by_email[e], dbid)
            else:
                by_email[e] = dbid
        for p in entry['phones']:
            if not p:
                continue
            if p in by_phone:
                union(by_phone[p], dbid)
            else:
                by_phone[p] = dbid

    canonical_map = {dbid: find(dbid) for dbid in directory}

    merged_directory: dict = {}
    for dbid, entry in directory.items():
        canon = canonical_map[dbid]
        target = merged_directory.setdefault(canon, {
            'db_id': canon, 'names': set(), 'emails': set(), 'phones': set(),
        })
        target['names']  |= entry['names']
        target['emails'] |= entry['emails']
        target['phones'] |= entry['phones']

    merged_name_to_dbids: dict = {}
    for name, ids in name_to_dbids.items():
        merged_name_to_dbids.setdefault(name, set()).update(canonical_map.get(i, i) for i in ids)

    return merged_directory, merged_name_to_dbids, canonical_map


# ── Full load ─────────────────────────────────────────────────────────────

def _do_load():
    global _loading_now
    warnings = []
    try:
        service  = _build_service()
        all_tabs = _list_tabs(service)
        month_map = _classify_tabs(all_tabs)

        all_raw = []
        # directory keyed by db_id
        directory: dict = {}
        # per-name-normalized -> set(db_id), to detect collisions
        name_to_dbids: dict = {}
        rollup_by_month: dict = {}

        for (year, mnum), tabs in sorted(month_map.items()):
            month_key = f'{year:04d}-{mnum:02d}'
            month_label = f'{_MONTH_LABEL[mnum]} {year}'
            rollup_totals: dict = {}

            for tab in tabs:
                try:
                    grid = _fetch_tab(service, tab)
                except Exception as exc:
                    warnings.append(f'{tab}: fetch failed ({exc})')
                    continue

                raw_records, roster_rows, rollup_rows = _parse_tab(grid, month_key)
                all_raw.extend(raw_records)

                for rr in roster_rows:
                    dbid = rr['db_id']
                    entry = directory.setdefault(dbid, {
                        'db_id': dbid, 'names': set(), 'emails': set(), 'phones': set(),
                    })
                    if _looks_like_name(rr['name']):
                        entry['names'].add(rr['name'])
                        nname = _norm_name(rr['name'])
                        name_to_dbids.setdefault(nname, set()).add(dbid)
                    if rr['email'] and '@' in rr['email']:
                        entry['emails'].add(_norm_email(rr['email']))
                    if rr['phone']:
                        entry['phones'].add(re.sub(r'\D', '', rr['phone']))

                for row in rollup_rows:
                    key = _norm_name(row['name'])
                    prev = rollup_totals.get(key, 0.0)
                    rollup_totals[key] = prev + row['amount']

            rollup_by_month[month_key] = {'label': month_label, 'totals': rollup_totals}

        directory, name_to_dbids, _canonical_map = _merge_directory_by_contact(directory, name_to_dbids)

        collisions = {n: ids for n, ids in name_to_dbids.items() if len(ids) > 1}
        if collisions:
            warnings.append(f'{len(collisions)} interviewer name(s) map to multiple DB IDs '
                             f'across tabs (cannot be told apart from raw data alone): '
                             + ', '.join(sorted(collisions)[:10]))

        # Resolve a canonical display name per db_id (longest / most complete variant)
        for entry in directory.values():
            entry['name'] = max(entry['names'], key=len) if entry['names'] else ''

        # name -> db_id resolution table (only for unambiguous names)
        name_to_single_dbid = {n: next(iter(ids)) for n, ids in name_to_dbids.items() if len(ids) == 1}

        # ── Attribute raw records to a db_id, aggregate per person per month ──
        person_month: dict = {}   # (db_id) -> {month_key: {'count', 'amount', 'rows': []}}
        unmatched = 0
        for rec in all_raw:
            nname = _norm_name(rec['person'])
            dbid = name_to_single_dbid.get(nname)
            if dbid is None:
                # ambiguous or unknown — fall back to a name-based pseudo identity
                dbid = f'name::{nname}'
                unmatched += 1
            slot = person_month.setdefault(dbid, {})
            m = slot.setdefault(rec['month'], {'count': 0, 'amount': 0.0, 'rows': []})
            m['count'] += 1
            m['amount'] += rec['amount']
            m['rows'].append(rec)

        if unmatched:
            warnings.append(f'{unmatched} interview row(s) attributed by name only '
                             f'(no unique DB ID match) — grouped under a name-based identity.')

        # cross-check against the sheet's own rollup 'Amount' per month/person
        mismatches = 0
        for month_key, mdata in rollup_by_month.items():
            for nname, expected in mdata['totals'].items():
                dbid = name_to_single_dbid.get(nname)
                actual = 0.0
                if dbid and dbid in person_month:
                    actual = person_month[dbid].get(month_key, {}).get('amount', 0.0)
                elif f'name::{nname}' in person_month:
                    actual = person_month[f'name::{nname}'].get(month_key, {}).get('amount', 0.0)
                if abs(actual - expected) > 1:
                    mismatches += 1
        if mismatches:
            warnings.append(f'{mismatches} person/month total(s) differ from the sheet\'s own '
                             f'rollup by more than a rounding error — check payouts_loader parsing.')

        _cache['df']        = person_month
        _cache['directory'] = directory
        _cache['months']    = {k: v['label'] for k, v in rollup_by_month.items()}
        _cache['warnings']  = warnings
        _cache['tab_count'] = sum(len(t) for t in month_map.values())
        _cache['ts']        = time.time()
        print(f'[payouts_loader] Loaded {len(all_raw)} interview rows across '
              f'{_cache["tab_count"]} tabs, {len(directory)} interviewers. '
              f'Warnings: {len(warnings)}', flush=True)
        for w in warnings:
            print(f'[payouts_loader] WARNING: {w}', flush=True)

    except Exception as exc:
        warnings.append(f'load failed: {exc}')
        _cache['warnings'] = warnings
        print(f'[payouts_loader] Load failed: {exc}', flush=True)
    finally:
        _loading_now = False
        _load_lock.release()


def load_data(force: bool = False):
    """Ensure cache is populated; trigger background refresh if stale. Blocks on first load."""
    global _loading_now
    now = time.time()
    if not force and _cache['df'] is not None and (now - _cache['ts']) < CACHE_TTL:
        return
    if not _loading_now:
        if _load_lock.acquire(blocking=False):
            _loading_now = True
            threading.Thread(target=_do_load, daemon=True).start()
    if _cache['df'] is not None:
        return
    deadline = time.time() + 300
    while _loading_now and time.time() < deadline:
        time.sleep(1)


def get_last_loaded() -> str:
    if _cache['ts']:
        import datetime
        return datetime.datetime.fromtimestamp(_cache['ts']).strftime('%d %b %Y %H:%M')
    return 'Never'


def get_warnings() -> list:
    return _cache.get('warnings', [])


def get_tab_count() -> int:
    return _cache.get('tab_count', 0)


# ── Identity lookup (for auth) ──────────────────────────────────────────────

def find_db_id_by_email(email: str):
    load_data()
    target = _norm_email(email)
    if not target:
        return None
    for dbid, entry in (_cache['directory'] or {}).items():
        if target in entry['emails']:
            return dbid
    return None


def get_emails_for_db_id(db_id: str) -> set:
    load_data()
    entry = (_cache['directory'] or {}).get(db_id)
    return set(entry['emails']) if entry else set()


def get_display_name(db_id: str) -> str:
    load_data()
    entry = (_cache['directory'] or {}).get(db_id)
    return entry['name'] if entry else db_id


def get_display_name_any(db_id: str) -> str:
    """Like get_display_name, but also resolves name-based pseudo identities
    (db_id == 'name::<normalized name>') created for unmatched interview rows."""
    load_data()
    entry = (_cache['directory'] or {}).get(db_id)
    if entry:
        return entry['name']
    if db_id.startswith('name::'):
        return db_id[len('name::'):].title()
    return db_id


def get_all_interviewers() -> list:
    """Admin directory: every known interviewer (roster + name-only pseudo
    identities that received a payout), with all-time totals."""
    load_data()
    directory    = _cache['directory'] or {}
    person_month = _cache['df'] or {}

    def totals_for(dbid):
        months = person_month.get(dbid, {})
        amount = sum(m['amount'] for m in months.values())
        count  = sum(m['count'] for m in months.values())
        return round(amount, 2), int(count), len(months)

    rows = []
    for dbid, entry in directory.items():
        amount, count, months_active = totals_for(dbid)
        rows.append({
            'db_id': dbid, 'name': entry['name'],
            'email': sorted(entry['emails'])[0] if entry['emails'] else '',
            'phone': sorted(entry['phones'])[0] if entry['phones'] else '',
            'total_amount': amount, 'total_count': count, 'months_active': months_active,
        })

    for dbid in person_month:
        if dbid in directory:
            continue
        amount, count, months_active = totals_for(dbid)
        rows.append({
            'db_id': dbid, 'name': get_display_name_any(dbid),
            'email': '', 'phone': '', 'total_amount': amount, 'total_count': count,
            'months_active': months_active,
        })

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def get_org_monthly_totals(db_ids: set = None) -> list:
    """Month-by-month totals, oldest first — feeds the admin trend chart.
    Pass db_ids to restrict the total to a specific set of interviewers
    (e.g. the curated panelist roster) instead of everyone in the sheet."""
    load_data()
    person_month = _cache['df'] or {}
    months_meta  = _cache['months'] or {}

    totals: dict = {}
    for dbid, slots in person_month.items():
        if db_ids is not None and dbid not in db_ids:
            continue
        for month_key, m in slots.items():
            t = totals.setdefault(month_key, {'amount': 0.0, 'count': 0})
            t['amount'] += m['amount']
            t['count']  += m['count']

    return [
        {'month': month_key, 'label': months_meta.get(month_key, month_key),
         'amount': round(totals[month_key]['amount'], 2), 'count': int(totals[month_key]['count'])}
        for month_key in sorted(totals.keys())
    ]


# ── Payouts for a given identity ─────────────────────────────────────────────

def get_payouts_for(db_id: str) -> dict:
    load_data()
    person_month = (_cache['df'] or {}).get(db_id, {})
    months_meta  = _cache['months'] or {}

    months = []
    details = {}
    for month_key in sorted(person_month.keys(), reverse=True):
        m = person_month[month_key]
        label = months_meta.get(month_key, month_key)
        months.append({'month': month_key, 'label': label,
                        'count': int(m['count']), 'amount': round(m['amount'], 2)})
        def _sort_key(rec):
            ts = _parse_date(rec.get('date_raw'))
            return (ts is None, ts or _DATETIME_MIN)

        rows = []
        for rec in sorted(m['rows'], key=_sort_key):
            ts = _parse_date(rec.get('date_raw'))
            attendance = rec.get('attendance', 'done')
            rows.append({
                'candidate': rec['candidate'], 'role': rec['role'],
                'date': ts.strftime('%d %b %Y %H:%M') if ts is not None else str(rec.get('date_raw') or ''),
                'amount': rec['amount'],
                'attendance': attendance,
                'attendance_label': ATTENDANCE_LABELS.get(attendance, ATTENDANCE_LABELS['done']),
            })
        details[month_key] = rows

    return {'months': months, 'details': details}
