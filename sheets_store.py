"""Generic Google-Sheets-backed row store for this app's own state.

Separate from payouts_loader.py's SHEET_ID (finance's read-only source of
truth) -- this is a small spreadsheet used for data this app needs to
*write*: PINs, sign-off acknowledgments, and the manual panelist roster
overlay. One tab per record type, one row per record.

The service account's GCP project doesn't have the Drive API enabled, so it
can't create/own a spreadsheet itself (Sheets API access alone isn't
enough to create a new file). Instead: a human creates one blank Google
Sheet and shares it with the service account as Editor; this module then
bootstraps the tabs/headers on it. See ensure_app_state_sheet().
"""
import os
import json
import time
import socket
import threading

from google.oauth2 import service_account
from googleapiclient.discovery import build

# See payouts_loader.py for why this matters: without a process-wide socket
# timeout, a hung network call here has no exception to be caught by.
socket.setdefaulttimeout(45)

SA_FILE = os.environ.get('SA_FILE_PATH') or os.path.join(os.path.dirname(__file__), 'service_account.json')
SCOPES  = ['https://www.googleapis.com/auth/spreadsheets']

_SHEET_ID_FILE = os.path.join(os.path.dirname(__file__), 'data', 'app_state_sheet_id.json')
_ADMIN_FILE    = os.path.join(os.path.dirname(__file__), 'data', 'admin_emails.json')

SERVICE_ACCOUNT_EMAIL = None  # filled in lazily from service_account.json

TABS = {
    'pins':            ['email', 'pin', 'assigned_at'],
    'acknowledgments': ['email', 'db_id', 'name', 'month', 'amount', 'acknowledged_at'],
    'panelists':       ['email', 'name', 'phone', 'status', 'added_at'],
}

CACHE_TTL = 60  # seconds

_lock = threading.Lock()
_cache: dict = {}          # tab -> {'rows': [...], 'ts': float}
_service = None
_sheet_id = None


def _sa_info() -> dict:
    """The service account key as a dict, from whichever source is
    available -- GOOGLE_SERVICE_ACCOUNT_JSON (serverless hosts with no
    mountable file, e.g. Vercel) takes priority over SA_FILE_PATH (a
    mounted secret file, e.g. on Render) or a local file for dev."""
    raw = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if raw:
        return json.loads(raw)
    with open(SA_FILE, encoding='utf-8') as f:
        return json.load(f)


def _build_service():
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_info(_sa_info(), scopes=SCOPES)
        _service = build('sheets', 'v4', credentials=creds, static_discovery=True)
    return _service


def _load_admin_emails() -> list:
    if os.path.isfile(_ADMIN_FILE):
        with open(_ADMIN_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []


def get_service_account_email() -> str:
    global SERVICE_ACCOUNT_EMAIL
    if SERVICE_ACCOUNT_EMAIL is None:
        SERVICE_ACCOUNT_EMAIL = _sa_info()['client_email']
    return SERVICE_ACCOUNT_EMAIL


class AppStateNotConfigured(Exception):
    pass


def get_sheet_id() -> str:
    """Resolve the app-state spreadsheet ID: env var, then local cache file.
    Raises AppStateNotConfigured with setup instructions if neither is set."""
    global _sheet_id
    if _sheet_id:
        return _sheet_id
    env_id = os.environ.get('APP_STATE_SHEET_ID')
    if env_id:
        _sheet_id = env_id
        return _sheet_id
    if os.path.isfile(_SHEET_ID_FILE):
        with open(_SHEET_ID_FILE, encoding='utf-8') as f:
            _sheet_id = json.load(f)['sheet_id']
        return _sheet_id
    raise AppStateNotConfigured(
        'No app-state sheet configured. Create a blank Google Sheet, share it as '
        f'Editor with {get_service_account_email()}, then run '
        '`python -c "import sheets_store; sheets_store.bootstrap(\'<sheet id from its URL>\')"`'
    )


def bootstrap(sheet_id: str):
    """One-time setup against a human-created, SA-shared blank sheet: rename/
    create the pins/acknowledgments/panelists tabs with headers, persist the
    ID locally. Safe to re-run (won't duplicate tabs)."""
    global _sheet_id
    service = _build_service()
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing_titles = {s['properties']['title']: s['properties']['sheetId'] for s in meta['sheets']}

    requests = []
    for tab in TABS:
        if tab not in existing_titles:
            requests.append({'addSheet': {'properties': {'title': tab}}})
    if requests:
        service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={'requests': requests}).execute()

    data = [{'range': f"'{tab}'!A1", 'values': [headers]} for tab, headers in TABS.items()]
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id, body={'valueInputOption': 'RAW', 'data': data},
    ).execute()

    os.makedirs(os.path.dirname(_SHEET_ID_FILE), exist_ok=True)
    with open(_SHEET_ID_FILE, 'w', encoding='utf-8') as f:
        json.dump({'sheet_id': sheet_id}, f)
    _sheet_id = sheet_id
    print(f'[sheets_store] App-state sheet ready: '
          f'https://docs.google.com/spreadsheets/d/{sheet_id}/edit', flush=True)
    return sheet_id


def ensure_app_state_sheet() -> str:
    """Call at startup to confirm the sheet is configured; raises with setup
    instructions if not (see get_sheet_id)."""
    return get_sheet_id()


def _fetch_tab_raw(tab: str) -> list:
    service = _build_service()
    res = service.spreadsheets().values().get(
        spreadsheetId=get_sheet_id(), range=f"'{tab}'!A1:Z10000",
    ).execute()
    return res.get('values', [])


def read_tab(tab: str, force: bool = False) -> list:
    """Return this tab's rows as a list of dicts, keyed by its header row."""
    with _lock:
        entry = _cache.get(tab)
        if not force and entry and (time.time() - entry['ts']) < CACHE_TTL:
            return entry['rows']

    grid = _fetch_tab_raw(tab)
    if not grid:
        rows = []
    else:
        headers = grid[0]
        rows = []
        for r in grid[1:]:
            row = {headers[i]: (r[i] if i < len(r) else '') for i in range(len(headers))}
            if any(v for v in row.values()):
                rows.append(row)

    with _lock:
        _cache[tab] = {'rows': rows, 'ts': time.time()}
    return rows


def _invalidate(tab: str):
    with _lock:
        _cache.pop(tab, None)


def upsert_row(tab: str, key_cols: list, row: dict):
    """Update the first row matching all key_cols, or append a new one."""
    headers = TABS[tab]
    service = _build_service()
    sheet_id = get_sheet_id()

    grid = _fetch_tab_raw(tab)
    existing_headers = grid[0] if grid else headers
    match_row_idx = None
    for i, r in enumerate(grid[1:], start=2):  # sheet row numbers, 1-indexed + header
        rowd = {existing_headers[j]: (r[j] if j < len(r) else '') for j in range(len(existing_headers))}
        if all(str(rowd.get(k, '')) == str(row.get(k, '')) for k in key_cols):
            match_row_idx = i
            break

    values = [row.get(h, '') for h in headers]
    if match_row_idx is not None:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"'{tab}'!A{match_row_idx}",
            valueInputOption='RAW', body={'values': [values]},
        ).execute()
    else:
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=f"'{tab}'!A1",
            valueInputOption='RAW', insertDataOption='INSERT_ROWS',
            body={'values': [values]},
        ).execute()

    _invalidate(tab)
