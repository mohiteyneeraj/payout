"""5-digit PIN login for interviewers.

No accounts/passwords -- each person on file (interviewer roster + manually
onboarded panelists + admin list) gets a fixed 5-digit PIN, auto-assigned
the first time they're seen and stored in the app-state Sheet's 'pins' tab
(see sheets_store.py). Verifying a PIN never reveals whether an email is
recognized. A panelist marked 'removed' in the roster overlay can no longer
log in even with a correct PIN.
"""
import os
import re
import json
import time
import random
import threading

import panelists
import sheets_store as store

_ADMIN_FILE = os.path.join(os.path.dirname(__file__), 'data', 'admin_emails.json')

MAX_ATTEMPTS_PER_HOUR = 8

_lock = threading.Lock()
_attempt_log: dict = {}   # email -> [timestamp, ...] (last hour)


def _norm_email(email: str) -> str:
    return str(email or '').strip().lower()


def _admin_display_name(email: str) -> str:
    local = email.split('@')[0]
    parts = re.split(r'[._]+', local)
    return ' '.join(p.capitalize() for p in parts if p)


def _load_admin_emails() -> set:
    if os.path.isfile(_ADMIN_FILE):
        with open(_ADMIN_FILE, encoding='utf-8') as f:
            return {_norm_email(e) for e in json.load(f)}
    return set()


def _new_pin(used: set) -> str:
    while True:
        pin = f'{random.randint(0, 99999):05d}'
        if pin not in used:
            return pin


def sync_pins() -> dict:
    """Assign a PIN to every known interviewer/panelist/admin email that
    doesn't have one yet. Existing PINs are never changed. Returns
    {email: pin}."""
    with _lock:
        rows = store.read_tab('pins')
        pins = {r['email']: r['pin'] for r in rows if r.get('email')}
        used = set(pins.values())

        known_emails = set(_load_admin_emails())
        for row in panelists.get_roster():
            if row.get('email') and row.get('status') != 'removed':
                known_emails.add(_norm_email(row['email']))

        for email in known_emails:
            if email and email not in pins:
                pin = _new_pin(used)
                pins[email] = pin
                used.add(pin)
                store.upsert_row('pins', ['email'], {
                    'email': email, 'pin': pin, 'assigned_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                })

        return pins


def get_pin_for(email: str):
    """Admin helper: look up the PIN for a given email (assigns one if new)."""
    return sync_pins().get(_norm_email(email))


def _rate_limited(email: str) -> bool:
    now = time.time()
    hist = [t for t in _attempt_log.get(email, []) if now - t < 3600]
    _attempt_log[email] = hist
    return len(hist) >= MAX_ATTEMPTS_PER_HOUR


def verify_pin(email: str, pin: str) -> dict:
    """Returns {'ok': True, 'db_id', 'name', 'is_admin'} or {'ok': False, 'error'}."""
    norm = _norm_email(email)
    pin  = str(pin or '').strip()

    if not norm or '@' not in norm:
        return {'ok': False, 'error': 'Enter a valid email.'}

    with _lock:
        if _rate_limited(norm):
            return {'ok': False, 'error': 'Too many attempts. Try again later.'}
        _attempt_log.setdefault(norm, []).append(time.time())

    if panelists.is_removed(norm):
        return {'ok': False, 'error': 'Incorrect email or PIN.'}

    expected = sync_pins().get(norm)
    if not expected or pin != expected:
        return {'ok': False, 'error': 'Incorrect email or PIN.'}

    is_admin = norm in _load_admin_emails()
    identity = panelists.find_identity_by_email(norm)
    if not identity and not is_admin:
        return {'ok': False, 'error': 'Incorrect email or PIN.'}

    db_id = identity['db_id'] if identity else None
    name = identity['name'] if identity else _admin_display_name(norm)
    return {'ok': True, 'db_id': db_id, 'name': name, 'is_admin': is_admin, 'email': norm}
