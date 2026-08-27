"""Interviewer Payouts — Flask backend.

Interviewers log in with the email on file in the payout sheet's roster
block plus a fixed 5-digit PIN (no password) and see their own
month-by-month payout totals with interview-level detail, with the option
to acknowledge/sign off on each month starting from ACK_START_MONTH.
"""
import os
import csv
import io
import json
import time
import secrets
import threading
import datetime
from flask import Flask, jsonify, request, send_from_directory, session, Response

import auth
import payouts_loader as pl
import panelists
import sheets_store as store

app = Flask(__name__, static_folder='static')

_SECRET_FILE = os.path.join(os.path.dirname(__file__), 'data', 'secret_key.json')

# First month panelists are asked to acknowledge/sign off on their payout —
# earlier months stay informational-only (no sign-off asked retroactively).
ACK_START_MONTH = os.environ.get('ACK_START_MONTH', '2026-08')


def _get_secret_key() -> str:
    env_key = os.environ.get('FLASK_SECRET_KEY')
    if env_key:
        return env_key
    if os.path.isfile(_SECRET_FILE):
        with open(_SECRET_FILE, encoding='utf-8') as f:
            return json.load(f)['key']
    key = secrets.token_hex(32)
    os.makedirs(os.path.dirname(_SECRET_FILE), exist_ok=True)
    with open(_SECRET_FILE, 'w', encoding='utf-8') as f:
        json.dump({'key': key}, f)
    return key


app.secret_key = _get_secret_key()

AUTO_SYNC_INTERVAL = 1800  # 30 minutes


def _preload():
    time.sleep(1)
    try:
        pl.load_data()
        print('[app] Payout data pre-loaded successfully', flush=True)
    except Exception as exc:
        print(f'[app] Pre-load failed: {exc}', flush=True)


def _auto_sync_loop():
    while True:
        time.sleep(AUTO_SYNC_INTERVAL)
        try:
            pl.load_data(force=True)
            print('[auto-sync] Refresh complete', flush=True)
        except Exception as exc:
            print(f'[auto-sync] Error: {exc}', flush=True)


# ── Serve frontend ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    result = auth.verify_pin(data.get('email', ''), data.get('pin', ''))
    if result.get('ok'):
        session['authenticated'] = True
        session['db_id']   = result.get('db_id')
        session['email']   = result.get('email')
        session['name']    = result['name']
        session['is_admin'] = result.get('is_admin', False)
        session.permanent = True
        result['has_own_payouts'] = result.get('db_id') is not None
    return jsonify(result)


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/me')
def api_me():
    if not session.get('authenticated'):
        return jsonify({'ok': False}), 401
    return jsonify({
        'ok': True, 'name': session.get('name'),
        'is_admin': session.get('is_admin', False),
        'has_own_payouts': session.get('db_id') is not None,
    })


# ── Payouts ───────────────────────────────────────────────────────────────────

def _apply_ack_status(data: dict, email: str) -> dict:
    """Mutate a get_payouts_for() result in place: mark each month
    acknowledged/not, and flag which months are even eligible for sign-off."""
    norm = (email or '').strip().lower()
    acks = {r['month']: r for r in store.read_tab('acknowledgments') if r.get('email') == norm}
    for m in data['months']:
        ack = acks.get(m['month'])
        m['ack_eligible']   = m['month'] >= ACK_START_MONTH
        m['acknowledged']   = bool(ack)
        m['acknowledged_at'] = ack.get('acknowledged_at') if ack else None
    data['ack_start_month'] = ACK_START_MONTH
    return data


@app.route('/api/payouts')
def api_payouts():
    if not session.get('db_id'):
        return jsonify({'ok': False, 'error': 'Not logged in'}), 401
    data = pl.get_payouts_for(session['db_id'])
    _apply_ack_status(data, session.get('email', ''))
    return jsonify({'ok': True, 'name': session.get('name'), **data})


@app.route('/api/payouts/acknowledge', methods=['POST'])
def api_payouts_acknowledge():
    if not session.get('db_id'):
        return jsonify({'ok': False, 'error': 'Not logged in'}), 401
    month = (request.get_json(silent=True) or {}).get('month', '')
    if month < ACK_START_MONTH:
        return jsonify({'ok': False, 'error': 'This month is not open for sign-off.'}), 400

    data = pl.get_payouts_for(session['db_id'])
    match = next((m for m in data['months'] if m['month'] == month), None)
    if not match:
        return jsonify({'ok': False, 'error': 'No payout found for that month.'}), 404

    now = time.strftime('%Y-%m-%d %H:%M:%S')
    store.upsert_row('acknowledgments', ['email', 'month'], {
        'email': session.get('email', ''), 'db_id': session['db_id'], 'name': session.get('name', ''),
        'month': month, 'amount': match['amount'], 'acknowledged_at': now,
    })
    return jsonify({'ok': True, 'acknowledged_at': now})


# ── Admin ─────────────────────────────────────────────────────────────────────

def _require_admin():
    return bool(session.get('authenticated') and session.get('is_admin'))


@app.route('/api/admin/interviewers')
def api_admin_interviewers():
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    return jsonify({'ok': True, 'interviewers': pl.get_all_interviewers()})


@app.route('/api/admin/payouts/<path:db_id>')
def api_admin_payouts(db_id):
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    data = pl.get_payouts_for(db_id)
    email = next((r['email'] for r in panelists.get_roster() if r['db_id'] == db_id), '')
    _apply_ack_status(data, email)
    return jsonify({'ok': True, 'name': pl.get_display_name_any(db_id), **data})


@app.route('/api/admin/summary')
def api_admin_summary():
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    return jsonify({'ok': True, 'monthly': pl.get_org_monthly_totals()})


@app.route('/api/admin/pins')
def api_admin_pins():
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    return jsonify({'ok': True, 'pins': auth.sync_pins()})


@app.route('/api/admin/panelists')
def api_admin_panelists():
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    return jsonify({'ok': True, 'panelists': panelists.get_roster()})


@app.route('/api/admin/panelists', methods=['POST'])
def api_admin_panelists_add():
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    data = request.get_json(silent=True) or {}
    try:
        panelists.add_panelist(data.get('name', ''), data.get('email', ''), data.get('phone', ''))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    auth.sync_pins()
    return jsonify({'ok': True})


@app.route('/api/admin/panelists/<path:email>/remove', methods=['POST'])
def api_admin_panelists_remove(email):
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    panelists.remove_panelist(email)
    return jsonify({'ok': True})


@app.route('/api/admin/panelists/<path:email>/restore', methods=['POST'])
def api_admin_panelists_restore(email):
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    panelists.restore_panelist(email)
    return jsonify({'ok': True})


@app.route('/api/admin/export.csv')
def api_admin_export_csv():
    if not _require_admin():
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Name', 'Email', 'Total Interviews', 'Total Amount'])
    for row in pl.get_all_interviewers():
        writer.writerow([row['name'], row['email'], row['total_count'], row['total_amount']])
    return Response(buf.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=interviewer_payouts.csv',
    })


@app.route('/api/status')
def api_status():
    return jsonify({
        'ok': True,
        'last_loaded': pl.get_last_loaded(),
        'tab_count':   pl.get_tab_count(),
        'warnings':    pl.get_warnings(),
    })


if __name__ == '__main__':
    app.permanent_session_lifetime = datetime.timedelta(days=30)
    threading.Thread(target=_preload,        daemon=True).start()
    threading.Thread(target=_auto_sync_loop, daemon=True).start()
    app.run(debug=False, host='0.0.0.0', port=5001)
