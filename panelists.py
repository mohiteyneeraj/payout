"""Panelist roster: an admin-curated allowlist over the derived payout data.

payouts_loader.get_all_interviewers() is fully derived from the payout
sheet's roster blocks and gets rebuilt from scratch on every refresh -- it
has no concept of "who's actually an active panelist right now" and no way
to onboard someone before their first paid interview. The 'panelists' tab
in the app-state sheet (see sheets_store.py) is the source of truth for
that: only emails listed there with status 'active' are considered part of
the roster at all -- for login, for the admin panelist list, everywhere.

- 'active' overlay row with no derived match -> manually onboarded panelist
  who hasn't been paid yet (shown with no payout history).
- 'active' overlay row matching a derived interviewer -> shown normally.
- 'removed' overlay row, or no overlay row at all -> excluded entirely
  (and blocks login), even if the payout sheet still lists them.
"""
import re
import threading

import payouts_loader as pl
import sheets_store as store


def _norm_email(v) -> str:
    return str(v or '').strip().lower()


def _load_overlay() -> dict:
    """Return {normalized_email: overlay_row_dict}."""
    return {_norm_email(r.get('email')): r for r in store.read_tab('panelists') if r.get('email')}


def _allowed_emails(overlay: dict) -> set:
    return {email for email, r in overlay.items() if r.get('status') == 'active'}


def get_roster() -> list:
    """Every panelist an admin should see: allowlisted derived (real payout
    data) rows, plus manually-onboarded (not-yet-paid) rows."""
    overlay = _load_overlay()
    allowed = _allowed_emails(overlay)
    derived = pl.get_all_interviewers()

    rows = []
    matched_emails = set()
    for r in derived:
        emails = pl.get_emails_for_db_id(r['db_id']) or ({_norm_email(r['email'])} if r.get('email') else set())
        hit = emails & allowed
        if not hit:
            continue
        matched_emails |= hit
        ov = overlay.get(_norm_email(r.get('email')))
        rows.append({
            'db_id': r['db_id'], 'name': r['name'], 'email': r.get('email', ''),
            'phone': r.get('phone') or (ov.get('phone') if ov else '') or '',
            'status': 'active', 'is_manual': False,
            'total_amount': r['total_amount'], 'total_count': r['total_count'],
            'months_active': r['months_active'],
        })

    for email in allowed - matched_emails:
        ov = overlay[email]
        rows.append({
            'db_id': 'manual::' + email, 'name': ov.get('name', ''), 'email': ov.get('email', ''),
            'phone': ov.get('phone', ''), 'status': 'active', 'is_manual': True,
            'total_amount': 0.0, 'total_count': 0, 'months_active': 0,
        })

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def get_removed() -> list:
    """Panelists explicitly marked removed (for the admin UI's restore action)."""
    overlay = _load_overlay()
    return [
        {'email': r.get('email', ''), 'name': r.get('name', ''), 'phone': r.get('phone', '')}
        for r in overlay.values() if r.get('status') == 'removed'
    ]


def find_identity_by_email(email: str):
    """Returns {'db_id', 'name', 'is_manual'} or None. Used by auth.py.
    Only emails allowlisted (status='active') in the panelists tab can log in."""
    norm = _norm_email(email)
    if not norm:
        return None
    overlay = _load_overlay()
    if norm not in _allowed_emails(overlay):
        return None

    db_id = pl.find_db_id_by_email(norm)
    if db_id:
        return {'db_id': db_id, 'name': pl.get_display_name(db_id), 'is_manual': False}
    return {'db_id': 'manual::' + norm, 'name': overlay[norm].get('name', ''), 'is_manual': True}


def is_removed(email: str) -> bool:
    norm = _norm_email(email)
    overlay = _load_overlay()
    return norm not in _allowed_emails(overlay)


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def add_panelist(name: str, email: str, phone: str):
    norm = _norm_email(email)
    if not norm or '@' not in norm:
        raise ValueError('A valid email is required.')
    store.upsert_row('panelists', ['email'], {
        'email': norm, 'name': str(name or '').strip(),
        'phone': re.sub(r'\D', '', str(phone or '')), 'status': 'active',
        'added_at': _now(),
    })


def remove_panelist(email: str):
    norm = _norm_email(email)
    existing = _load_overlay().get(norm, {})
    store.upsert_row('panelists', ['email'], {
        'email': norm, 'name': existing.get('name', ''), 'phone': existing.get('phone', ''),
        'status': 'removed', 'added_at': existing.get('added_at') or _now(),
    })


def restore_panelist(email: str):
    norm = _norm_email(email)
    existing = _load_overlay().get(norm, {})
    store.upsert_row('panelists', ['email'], {
        'email': norm, 'name': existing.get('name', ''), 'phone': existing.get('phone', ''),
        'status': 'active', 'added_at': existing.get('added_at') or _now(),
    })
