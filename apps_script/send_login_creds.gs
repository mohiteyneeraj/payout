/**
 * One-off blast: emails every active panelist their login (email + PIN)
 * for the Interview Payout portal and asks them to check & acknowledge
 * their payout. Pulls the panelist list and PINs straight from the app's
 * own admin API, so it always matches what's live.
 *
 * SETUP
 * 1. Go to script.google.com -> New project. Paste this whole file in.
 * 2. Fill in ADMIN_EMAIL / ADMIN_PIN below (your own admin login for the app).
 * 3. Run `sendPayoutCredsEmail` once with DRY_RUN = true. Open
 *    View > Logs (Ctrl+Enter) and check the recipient list looks right.
 * 4. First real run: authorize the script when Google prompts (it needs
 *    permission to send mail as you and to call the payout app).
 * 5. Set DRY_RUN = false and run again to actually send.
 *
 * SAFETY
 * Sent addresses are recorded in Script Properties, so re-running the
 * script (e.g. to catch stragglers added later) will only email people
 * who haven't received it yet. Call resetSentLog() to wipe that and
 * allow a full resend.
 */

const APP_URL     = 'https://payout-peach.vercel.app';
const ADMIN_EMAIL = 'neeraj.mohitey@cuemath.com'; // must be in admin_emails.json
const ADMIN_PIN   = 'FILL_ME_IN';                 // your admin PIN for the app
const DRY_RUN      = true;                          // flip to false to actually send
const SENT_LOG_KEY = 'PAYOUT_CREDS_SENT_EMAILS_V1';

function sendPayoutCredsEmail() {
  const cookie = adminLogin_();
  const panelists = fetchJson_('/api/admin/panelists', cookie).panelists;
  const pins = fetchJson_('/api/admin/pins', cookie).pins;

  const active = panelists.filter(p => p.status !== 'removed' && p.email);
  const alreadySent = getSentSet_();

  Logger.log(`${active.length} active panelist(s) on file. ${alreadySent.size} already sent to previously.`);

  let sent = 0, skippedNoPin = 0, skippedAlreadySent = 0, skippedNotCuemath = 0, failed = 0;
  const notCuemath = [];

  active.forEach(p => {
    const email = String(p.email).trim().toLowerCase();

    // Only ever mail a @cuemath.com address — never a personal Gmail/Yahoo/etc
    // one, even if that's the only email on file for this panelist.
    if (!email.endsWith('@cuemath.com')) {
      notCuemath.push(`${p.name} <${email}>`);
      skippedNotCuemath++;
      return;
    }

    if (alreadySent.has(email)) { skippedAlreadySent++; return; }

    const pin = pins[email];
    if (!pin) {
      Logger.log(`SKIP (no PIN on file): ${email}`);
      skippedNoPin++;
      return;
    }

    const subject = 'Your Interview Payout portal login — please check & acknowledge';
    const body = buildEmailBody_(p.name, email, pin);

    if (DRY_RUN) {
      Logger.log(`[DRY RUN] Would send to ${email} (${p.name})`);
      sent++;
      return;
    }

    try {
      MailApp.sendEmail({ to: email, subject: subject, htmlBody: body });
      markSent_(email);
      sent++;
      Utilities.sleep(300); // gentle pacing, avoid tripping mail rate limits
    } catch (err) {
      Logger.log(`FAILED to send to ${email}: ${err}`);
      failed++;
    }
  });

  Logger.log(`Done. sent=${sent} skipped_already_sent=${skippedAlreadySent} skipped_not_cuemath=${skippedNotCuemath} skipped_no_pin=${skippedNoPin} failed=${failed}`);
  if (notCuemath.length) {
    Logger.log(`\nNo @cuemath.com email on file — NOT emailed, needs manual onboarding first:\n` + notCuemath.join('\n'));
  }
}

function resetSentLog() {
  PropertiesService.getScriptProperties().deleteProperty(SENT_LOG_KEY);
  Logger.log('Sent log cleared.');
}

// ── Helpers ─────────────────────────────────────────────────────────────

function adminLogin_() {
  const res = UrlFetchApp.fetch(APP_URL + '/api/auth/login', {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ email: ADMIN_EMAIL, pin: ADMIN_PIN }),
    muteHttpExceptions: true,
  });
  const data = JSON.parse(res.getContentText());
  if (!data.ok || !data.is_admin) {
    throw new Error('Admin login failed — check ADMIN_EMAIL/ADMIN_PIN: ' + res.getContentText());
  }
  const raw = res.getAllHeaders()['Set-Cookie'];
  const parts = Array.isArray(raw) ? raw : [raw];
  return parts.map(c => c.split(';')[0]).join('; ');
}

function fetchJson_(path, cookie) {
  const res = UrlFetchApp.fetch(APP_URL + path, {
    method: 'get',
    headers: { Cookie: cookie },
    muteHttpExceptions: true,
  });
  const data = JSON.parse(res.getContentText());
  if (!data.ok) throw new Error(`GET ${path} failed: ` + res.getContentText());
  return data;
}

function getSentSet_() {
  const raw = PropertiesService.getScriptProperties().getProperty(SENT_LOG_KEY);
  return new Set(raw ? JSON.parse(raw) : []);
}

function markSent_(email) {
  const set = getSentSet_();
  set.add(email);
  PropertiesService.getScriptProperties().setProperty(SENT_LOG_KEY, JSON.stringify([...set]));
}

function buildEmailBody_(name, email, pin) {
  const firstName = (name || '').split(' ')[0] || 'there';
  return `
    <p>Hi ${escapeHtml_(firstName)},</p>
    <p>The Interview Payout portal is now live — you can log in anytime to see your
    month-by-month interview payouts, with a per-candidate breakdown.</p>
    <p>
      <b>Portal:</b> <a href="${APP_URL}">${APP_URL}</a><br>
      <b>Email:</b> ${escapeHtml_(email)}<br>
      <b>PIN:</b> ${escapeHtml_(pin)}
    </p>
    <p>Once you're in, please open your latest month and click
    <b>"Acknowledge &amp; sign off"</b> to confirm the payout looks correct.
    This is required starting with August 2026.</p>
    <p>Your PIN is personal to you — please don't share it.</p>
    <p>Thanks,<br>Cuemath Hiring Team</p>
  `;
}

function escapeHtml_(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
