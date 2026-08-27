"""Panelist roster: derived payout-sheet directory + manual Sheets overlay.

payouts_loader.get_all_interviewers() is fully derived from the payout
sheet's roster blocks and gets rebuilt from scratch on every refresh, so it
can't hold anything an admin manually adds or removes. This module layers a
small manual overlay (the 'panelists' tab in the app-state sheet, see
sheets_store.py) on top of it:

- 'active' overlay rows for an email with no derived entry -> a manually
  onboarded panelist who hasn't been paid yet (no payout history).
- 'removed' overlay rows -> hide (and block login for) that email, even if
  the payout sheet still lists them.
"""
import re
import time
import threading

import payouts_loader as pl
import sheets_store as store


def _norm_email(v) -> str:
    return str(v or '').strip().lower()


def _load_overlay() -> dict:
    """Return {normalized_email: overlay_row_dict}."""
    return {_norm_email(r.get('email')): r for r in store.read_tab('panelists') if r.get('email')}


def get_roster() -> list:
    """Every panelist an admin should see: derived (real payout data) rows,
    manually-onboarded (not-yet-paid) rows, with removed ones flagged."""
    overlay = _load_overlay()
    derived = pl.get_all_interviewers()
    derived_emails = {_norm_email(r['email']) for r in derived if r.get('email')}

    rows = []
    for r in derived:
        email = _norm_email(r.get('email'))
        ov = overlay.get(email)
        status = 'removed' if (ov and ov.get('status') == 'removed') else 'active'
        rows.append({
            'db_id': r['db_id'], 'name': r['name'], 'email': r.get('email', ''),
            'phone': r.get('phone') or (ov.get('phone') if ov else '') or '',
            'status': status, 'is_manual': False,
            'total_amount': r['total_amount'], 'total_count': r['total_count'],
            'months_active': r['months_active'],
        })

    for email, ov in overlay.items():
        if email in derived_emails:
            continue
        rows.append({
            'db_id': 'manual::' + email, 'name': ov.get('name', ''), 'email': ov.get('email', ''),
            'phone': ov.get('phone', ''), 'status': ov.get('status', 'active'), 'is_manual': True,
            'total_amount': 0.0, 'total_count': 0, 'months_active': 0,
        })

    rows.sort(key=lambda r: r['name'].lower())
    return rows


def find_identity_by_email(email: str):
    """Returns {'db_id', 'name', 'is_manual'} or None. Used by auth.py."""
    norm = _norm_email(email)
    if not norm:
        return None
    db_id = pl.find_db_id_by_email(norm)
    if db_id:
        return {'db_id': db_id, 'name': pl.get_display_name(db_id), 'is_manual': False}

    overlay = _load_overlay()
    ov = overlay.get(norm)
    if ov and ov.get('status') == 'active':
        return {'db_id': 'manual::' + norm, 'name': ov.get('name', ''), 'is_manual': True}
    return None


def is_removed(email: str) -> bool:
    ov = _load_overlay().get(_norm_email(email))
    return bool(ov and ov.get('status') == 'removed')


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
