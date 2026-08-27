(function () {
  const screenEmail            = document.getElementById('screenEmail');
  const screenDashboard        = document.getElementById('screenDashboard');
  const screenAdminList        = document.getElementById('screenAdminList');
  const screenAdminPanelists   = document.getElementById('screenAdminPanelists');
  const screenAdminAnalytics   = document.getElementById('screenAdminAnalytics');
  const screenAdminAgreements  = document.getElementById('screenAdminAgreements');
  const screenAdminDetail      = document.getElementById('screenAdminDetail');
  const logoutBtn              = document.getElementById('logoutBtn');

  const adminNav      = document.getElementById('adminNav');
  const navMine       = document.getElementById('navMine');
  const navPayouts    = document.getElementById('navPayouts');
  const navPanelists  = document.getElementById('navPanelists');
  const navAnalytics  = document.getElementById('navAnalytics');
  const navAgreements = document.getElementById('navAgreements');

  const previewJump       = document.getElementById('previewJump');
  const previewJumpInput  = document.getElementById('previewJumpInput');
  const interviewerListEl = document.getElementById('interviewerList');
  const mainContent       = document.querySelector('.main-content');

  const adminSearch        = document.getElementById('adminSearch');
  const adminTable         = document.getElementById('adminTable');
  const adminSummary       = document.getElementById('adminSummary');
  const statusFooterAdmin  = document.getElementById('statusFooterAdmin');
  const adminBack          = document.getElementById('adminBack');
  const adminDetailName    = document.getElementById('adminDetailName');
  const adminDetailSummary = document.getElementById('adminDetailSummary');
  const adminDetailMonths  = document.getElementById('adminDetailMonths');

  const panelistsSummary  = document.getElementById('panelistsSummary');
  const panelistsSearch   = document.getElementById('panelistsSearch');
  const panelistsTable    = document.getElementById('panelistsTable');
  const addPanelistForm   = document.getElementById('addPanelistForm');
  const addPanelistMsg    = document.getElementById('addPanelistMsg');

  const emailForm  = document.getElementById('emailForm');
  const emailInput = document.getElementById('emailInput');
  const pinInput   = document.getElementById('pinInput');
  const emailMsg    = document.getElementById('emailMsg');

  const dashName    = document.getElementById('dashName');
  const dashSummary = document.getElementById('dashSummary');
  const dashStats   = document.getElementById('dashStats');
  const dashTrendChart = document.getElementById('dashTrendChart');
  const monthList   = document.getElementById('monthList');
  const statusFooter = document.getElementById('statusFooter');

  const adminStats           = document.getElementById('adminStats');
  const adminTrendChart      = document.getElementById('adminTrendChart');
  const topEarners           = document.getElementById('topEarners');
  const adminDetailStats     = document.getElementById('adminDetailStats');
  const adminDetailTrendChart = document.getElementById('adminDetailTrendChart');
  const adminDetailBannerName = document.getElementById('adminDetailBannerName');

  const DASH_SUBTABS = [
    [document.getElementById('dashSubPayoutsBtn'),   document.getElementById('dashSubPayouts')],
    [document.getElementById('dashSubAgreementBtn'), document.getElementById('dashSubAgreement')],
    [document.getElementById('dashSubFeedbackBtn'),  document.getElementById('dashSubFeedback')],
  ];
  const ADMIN_DETAIL_SUBTABS = [
    [document.getElementById('adminDetailSubPayoutsBtn'),   document.getElementById('adminDetailSubPayouts')],
    [document.getElementById('adminDetailSubAgreementBtn'), document.getElementById('adminDetailSubAgreement')],
    [document.getElementById('adminDetailSubFeedbackBtn'),  document.getElementById('adminDetailSubFeedback')],
  ];

  function wireSubTabs(pairs) {
    pairs.forEach(([btn, panel]) => {
      btn.addEventListener('click', () => {
        pairs.forEach(([b, p]) => { b.classList.remove('active'); p.classList.add('hidden'); });
        btn.classList.add('active');
        panel.classList.remove('hidden');
      });
    });
  }
  function resetSubTabs(pairs) {
    pairs.forEach(([b, p], i) => {
      b.classList.toggle('active', i === 0);
      p.classList.toggle('hidden', i !== 0);
    });
  }
  wireSubTabs(DASH_SUBTABS);
  wireSubTabs(ADMIN_DETAIL_SUBTABS);

  let payoutsCache   = null;
  let isAdmin        = false;
  let hasOwnPayouts  = false;
  let allInterviewers = [];
  let allPanelists    = [];
  let adminSort = { key: 'name', dir: 1 };

  const LOGGED_IN_SCREENS = [screenDashboard, screenAdminList, screenAdminPanelists,
                              screenAdminAnalytics, screenAdminAgreements, screenAdminDetail];
  const WIDE_SCREENS      = [screenAdminList, screenAdminPanelists, screenAdminAnalytics, screenAdminDetail];

  function showScreen(el) {
    [screenEmail, ...LOGGED_IN_SCREENS].forEach(s => s.classList.add('hidden'));
    el.classList.remove('hidden');
    const loggedIn = LOGGED_IN_SCREENS.includes(el);
    logoutBtn.classList.toggle('hidden', !loggedIn);
    adminNav.classList.toggle('hidden', !(loggedIn && isAdmin));
    navMine.classList.toggle('hidden', !hasOwnPayouts);
    previewJump.classList.toggle('hidden', !(loggedIn && isAdmin));
    navMine.classList.toggle('active', el === screenDashboard);
    navPayouts.classList.toggle('active', el === screenAdminList || el === screenAdminDetail);
    navPanelists.classList.toggle('active', el === screenAdminPanelists);
    navAnalytics.classList.toggle('active', el === screenAdminAnalytics);
    navAgreements.classList.toggle('active', el === screenAdminAgreements);
    mainContent.classList.toggle('wide', WIDE_SCREENS.includes(el));
  }

  function money(n) {
    return '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({
      headers: { 'Content-Type': 'application/json' },
    }, opts));
    return res.json();
  }

  function showLoading(container) {
    container.innerHTML = '<div class="loading-inline">Loading…</div>';
  }

  // ── Stat cards ────────────────────────────────────────────────────────
  function statCard({ label, value, sub, trendClass }) {
    return `
      <div class="stat-card">
        <div class="stat-label">${escapeHtml(label)}</div>
        <div class="stat-value">${value}</div>
        ${sub ? `<div class="stat-sub${trendClass ? ' ' + trendClass : ''}">${sub}</div>` : ''}
      </div>
    `;
  }

  function renderDashboardStats(container, data) {
    const months = data.months || [];
    const totalAmount = months.reduce((s, m) => s + m.amount, 0);
    const totalCount  = months.reduce((s, m) => s + m.count, 0);
    const avg = totalCount ? totalAmount / totalCount : 0;

    let trendSub = '—';
    let trendClass = '';
    if (months.length) {
      const current = months[0];
      trendSub = money(current.amount);
      if (months.length > 1) {
        const prev = months[1].amount;
        if (prev > 0) {
          const pct = Math.round(((current.amount - prev) / prev) * 100);
          trendClass = pct > 0 ? 'trend-up' : pct < 0 ? 'trend-down' : '';
          const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '';
          trendSub = `${money(current.amount)} <span class="${trendClass}">${arrow} ${Math.abs(pct)}% vs prior month</span>`;
        }
      }
    }

    container.innerHTML = [
      statCard({ label: 'Total earned', value: money(totalAmount), sub: `${totalCount} interview${totalCount === 1 ? '' : 's'}` }),
      statCard({ label: 'Avg / interview', value: money(avg) }),
      statCard({ label: 'Months active', value: months.length }),
      statCard({ label: 'Latest month', value: months.length ? months[0].label : '—', sub: trendSub }),
    ].join('');
  }

  // ── Screen 1: log in with email + PIN ─────────────────────────────────
  emailForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = emailInput.value.trim();
    const pin = pinInput.value.trim();
    const btn = emailForm.querySelector('button');
    btn.disabled = true;
    emailMsg.textContent = '';
    emailMsg.className = 'form-msg';
    try {
      const result = await api('/api/auth/login', {
        method: 'POST', body: JSON.stringify({ email, pin }),
      });
      if (result.ok) {
        isAdmin = !!result.is_admin;
        hasOwnPayouts = !!result.has_own_payouts;
        if (isAdmin) ensureInterviewersLoaded().then(populateInterviewerDatalist);
        if (hasOwnPayouts) {
          await loadDashboard();
        } else {
          await loadAdminList();
        }
      } else {
        emailMsg.textContent = result.error || 'Incorrect email or PIN.';
        emailMsg.className = 'form-msg error';
      }
    } catch (err) {
      emailMsg.textContent = 'Something went wrong. Try again.';
      emailMsg.className = 'form-msg error';
    } finally {
      btn.disabled = false;
    }
  });

  // ── Logout ────────────────────────────────────────────────────────────
  logoutBtn.addEventListener('click', async () => {
    await api('/api/auth/logout', { method: 'POST' });
    payoutsCache = null;
    emailInput.value = '';
    pinInput.value = '';
    showScreen(screenEmail);
  });

  // ── Dashboard ─────────────────────────────────────────────────────────
  async function loadDashboard() {
    showScreen(screenDashboard);
    resetSubTabs(DASH_SUBTABS);
    showLoading(monthList);
    dashStats.innerHTML = '';
    const data = await api('/api/payouts');
    if (!data.ok) {
      showScreen(screenEmail);
      return;
    }
    payoutsCache = data;
    dashName.textContent = data.name || '';

    const totalAmount = data.months.reduce((s, m) => s + m.amount, 0);
    const totalCount  = data.months.reduce((s, m) => s + m.count, 0);
    dashSummary.textContent = data.months.length
      ? `${money(totalAmount)} total across ${totalCount} interviews, ${data.months.length} month(s)`
      : 'No payout history found yet.';

    renderDashboardStats(dashStats, data);
    renderTrendChart(dashTrendChart, monthsToTrendRows(data.months), { title: 'Monthly earnings' });

    monthList.innerHTML = '';
    if (!data.months.length) {
      monthList.innerHTML = '<div class="empty-state">Nothing to show yet — check back after your next interview payout cycle.</div>';
    } else {
      data.months.forEach(m => monthList.appendChild(renderMonthCard(m, data.details[m.month] || [], { allowAcknowledge: true })));
    }

    const status = await api('/api/status');
    if (status.ok) {
      statusFooter.textContent = `Data last synced: ${status.last_loaded}`;
    }
  }

  function ackStatusHtml(month, allowAcknowledge) {
    if (!month.ack_eligible) return '';
    if (month.acknowledged) {
      return `<div class="ack-status-holder"><span class="ack-tag ack-done">✓ Signed off ${escapeHtml(month.acknowledged_at || '')}</span></div>`;
    }
    if (allowAcknowledge) {
      return `<div class="ack-status-holder"><button type="button" class="btn-outline ack-btn">Acknowledge &amp; sign off</button></div>`;
    }
    return `<div class="ack-status-holder"><span class="ack-tag ack-pending">Not yet acknowledged</span></div>`;
  }

  function renderMonthCard(month, rows, opts) {
    opts = opts || {};
    const card = document.createElement('div');
    card.className = 'month-card';

    const row = document.createElement('div');
    row.className = 'month-row';
    row.innerHTML = `
      <div>
        <div class="month-name">${month.label}</div>
        <div class="month-count">${month.count} interview${month.count === 1 ? '' : 's'}</div>
        ${ackStatusHtml(month, opts.allowAcknowledge)}
      </div>
      <div style="display:flex; align-items:center;">
        <div class="month-amount">${money(month.amount)}</div>
        <div class="month-chevron">▶</div>
      </div>
    `;

    const ackBtn = row.querySelector('.ack-btn');
    if (ackBtn) {
      ackBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        ackBtn.disabled = true;
        ackBtn.textContent = 'Signing off…';
        try {
          const result = await api('/api/payouts/acknowledge', {
            method: 'POST', body: JSON.stringify({ month: month.month }),
          });
          if (result.ok) {
            month.acknowledged = true;
            month.acknowledged_at = result.acknowledged_at;
            const holder = row.querySelector('.ack-status-holder');
            if (holder) holder.outerHTML = ackStatusHtml(month, true);
          } else {
            ackBtn.disabled = false;
            ackBtn.textContent = 'Acknowledge & sign off';
          }
        } catch (err) {
          ackBtn.disabled = false;
          ackBtn.textContent = 'Acknowledge & sign off';
        }
      });
    }

    const details = document.createElement('div');
    details.className = 'month-details hidden';
    details.innerHTML = rows.map(r => `
      <div class="detail-row">
        <div>
          <span class="detail-candidate">${escapeHtml(r.candidate || 'Candidate')}</span>
          <span class="detail-role">${escapeHtml(r.role)}</span>
          <div class="detail-meta">${escapeHtml(r.date || '')}</div>
        </div>
        <div class="detail-amount">${money(r.amount)}</div>
      </div>
    `).join('') || '<div class="detail-row"><div class="detail-meta">No interview-level detail available.</div></div>';

    row.addEventListener('click', () => {
      const isOpen = card.classList.toggle('open');
      details.classList.toggle('hidden', !isOpen);
    });

    card.appendChild(row);
    card.appendChild(details);
    return card;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // months come sorted newest-first for the card list; charts read left-to-right.
  function monthsToTrendRows(months) {
    return months.slice().reverse().map(m => ({
      label: m.label, shortLabel: shortMonthLabel(m.label),
      value: m.amount, sub: `${m.count} interview${m.count === 1 ? '' : 's'}`,
    }));
  }

  function shortMonthLabel(label) {
    const [month, year] = label.split(' ');
    return year ? `${month.slice(0, 3)} '${year.slice(2)}` : label.slice(0, 3);
  }

  // ── Charts (hand-rolled inline SVG — single series, brand yellow) ────
  function niceCeil(v) {
    if (v <= 0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    const norm = v / mag;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
    return step * mag;
  }

  function roundedTopBarPath(x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h));
    return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} `
         + `L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
  }

  // rows: [{ label, shortLabel, value, sub }], chronological ascending.
  function renderTrendChart(container, rows, opts) {
    opts = opts || {};
    const maxVal = rows && rows.length ? Math.max(...rows.map(r => r.value), 0) : 0;
    if (!rows || !rows.length || maxVal <= 0) {
      container.innerHTML = `<div class="chart-title">${escapeHtml(opts.title || '')}</div>`
        + `<div class="empty-state">Not enough data yet.</div>`;
      return;
    }
    const W = 640, H = 170, padL = 6, padR = 6, padT = 20, padB = 20;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const n = rows.length;
    const slotW = plotW / n;
    const barW = Math.max(4, Math.min(28, slotW - 6));
    const niceMax = niceCeil(maxVal);

    const bars = rows.map((r, i) => {
      const x = padL + i * slotW + (slotW - barW) / 2;
      const h = maxVal > 0 ? Math.max(2, (r.value / niceMax) * plotH) : 0;
      const y = padT + plotH - h;
      return Object.assign({}, r, { x, y, w: barW, h, i });
    });

    const latestIdx = n - 1;
    const maxIdx = bars.reduce((best, b, i) => b.value > bars[best].value ? i : best, 0);
    const gridVals = [0.5, 1].map(f => niceMax * f);
    const gridSvg = gridVals.map(v => {
      const y = padT + plotH - (v / niceMax) * plotH;
      return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" class="chart-grid"/>`;
    }).join('');

    const barsSvg = bars.map(b => `
      <path class="chart-bar" tabindex="0" role="img"
            aria-label="${escapeHtml(b.label)}: ${escapeHtml((opts.money || money)(b.value))}"
            data-i="${b.i}" d="${roundedTopBarPath(b.x, b.y, b.w, b.h, 4)}"/>
    `).join('');

    const valueLabelsSvg = bars.filter(b => b.i === latestIdx || b.i === maxIdx).map(b => `
      <text class="chart-value-label" x="${b.x + b.w / 2}" y="${Math.max(10, b.y - 6)}" text-anchor="middle">${escapeHtml((opts.money || money)(b.value))}</text>
    `).join('');

    // Thin x-axis labels on long ranges so they never overlap — cap at ~8 shown.
    const labelStride = Math.max(1, Math.ceil(n / 8));
    const xLabelsSvg = bars.filter(b => b.i % labelStride === 0 || b.i === latestIdx).map(b => `
      <text class="chart-x-label" x="${b.x + b.w / 2}" y="${H - 4}" text-anchor="middle">${escapeHtml(b.shortLabel || '')}</text>
    `).join('');

    container.innerHTML = `
      <div class="chart-title">${escapeHtml(opts.title || '')}</div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="chart-svg">
        ${gridSvg}${barsSvg}${valueLabelsSvg}${xLabelsSvg}
      </svg>
    `;

    const tooltip = document.createElement('div');
    tooltip.className = 'chart-tooltip hidden';
    container.appendChild(tooltip);

    const svgEl = container.querySelector('svg');
    container.querySelectorAll('.chart-bar').forEach(el => {
      const b = bars[+el.dataset.i];
      const show = () => {
        const valueEl = document.createElement('strong');
        valueEl.textContent = (opts.money || money)(b.value);
        const subEl = document.createElement('span');
        subEl.textContent = b.label + (b.sub ? ` · ${b.sub}` : '');
        tooltip.replaceChildren(valueEl, subEl);
        tooltip.classList.remove('hidden');
        const svgRect = svgEl.getBoundingClientRect();
        const scale = svgRect.width / W;
        const left = Math.min(Math.max((b.x + b.w / 2) * scale, 50), svgRect.width - 50);
        tooltip.style.left = left + 'px';
        tooltip.style.top = (b.y * scale) + 'px';
      };
      const hide = () => tooltip.classList.add('hidden');
      el.addEventListener('pointerenter', show);
      el.addEventListener('focus', show);
      el.addEventListener('pointerleave', hide);
      el.addEventListener('blur', hide);
    });
  }

  // rows: [{ label, value }], already sorted best-first.
  function renderLeaderboard(container, rows, opts) {
    opts = opts || {};
    if (!rows || !rows.length) {
      container.innerHTML = `<div class="chart-title">${escapeHtml(opts.title || '')}</div>`
        + `<div class="empty-state">No data yet.</div>`;
      return;
    }
    const maxVal = Math.max(...rows.map(r => r.value), 1);
    container.innerHTML = `
      <div class="chart-title">${escapeHtml(opts.title || '')}</div>
      <div class="leaderboard">
        ${rows.map((r, i) => `
          <div class="leaderboard-row">
            <div class="leaderboard-rank">${i + 1}</div>
            <div class="leaderboard-main">
              <div class="leaderboard-name">${escapeHtml(r.label)}</div>
              <div class="leaderboard-track"><div class="leaderboard-fill" style="width:${Math.max(3, r.value / maxVal * 100)}%"></div></div>
            </div>
            <div class="leaderboard-value">${escapeHtml((opts.money || money)(r.value))}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  // ── Admin: directory + drill-down ────────────────────────────────────
  navMine.addEventListener('click', () => loadDashboard());
  navPayouts.addEventListener('click', () => loadAdminList());
  navPanelists.addEventListener('click', () => loadAdminPanelists());
  navAnalytics.addEventListener('click', () => loadAdminAnalytics());
  navAgreements.addEventListener('click', () => showScreen(screenAdminAgreements));
  adminBack.addEventListener('click', () => loadAdminList());

  // ── Preview-as quick jump (debug shortcut) ───────────────────────────
  async function ensureInterviewersLoaded() {
    if (allInterviewers.length) return allInterviewers;
    const data = await api('/api/admin/interviewers');
    if (data.ok) allInterviewers = data.interviewers;
    return allInterviewers;
  }

  function populateInterviewerDatalist() {
    interviewerListEl.innerHTML = allInterviewers.map(i =>
      `<option value="${escapeHtml(i.name)}"></option>`).join('');
  }

  async function jumpToPreview() {
    const q = previewJumpInput.value.trim().toLowerCase();
    if (!q) return;
    const list = await ensureInterviewersLoaded();
    const match = list.find(i => i.name.toLowerCase() === q) ||
                  list.find(i => i.name.toLowerCase().includes(q));
    previewJumpInput.value = '';
    if (match) loadAdminDetail(match);
  }
  previewJumpInput.addEventListener('change', jumpToPreview);
  previewJumpInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') jumpToPreview();
  });

  async function loadAdminList() {
    showScreen(screenAdminList);
    showLoading(adminTable);
    adminStats.innerHTML = '';
    const data = await api('/api/admin/interviewers');
    if (!data.ok) { showScreen(screenEmail); return; }
    allInterviewers = data.interviewers;
    adminSearch.value = '';
    applyAdminSort();
    renderAdminTable(allInterviewers);

    const totalAmount = allInterviewers.reduce((s, i) => s + i.total_amount, 0);
    adminSummary.textContent = allInterviewers.length
      ? `${allInterviewers.length} interviewer(s), ${money(totalAmount)} paid all-time`
      : 'No interviewers found yet.';

    adminStats.innerHTML = [
      statCard({ label: 'Interviewers', value: allInterviewers.length }),
      statCard({ label: 'Paid all-time', value: money(totalAmount) }),
      statCard({ label: 'Avg / interviewer', value: money(allInterviewers.length ? totalAmount / allInterviewers.length : 0) }),
    ].join('');

    const status = await api('/api/status');
    if (status.ok) {
      statusFooterAdmin.textContent = `Data last synced: ${status.last_loaded}`;
    }
  }

  async function loadAdminAnalytics() {
    showScreen(screenAdminAnalytics);
    showLoading(adminTrendChart);
    showLoading(topEarners);

    const list = await ensureInterviewersLoaded();
    const top = list.slice().sort((a, b) => b.total_amount - a.total_amount).slice(0, 10)
      .map(i => ({ label: i.name, value: i.total_amount }));
    renderLeaderboard(topEarners, top, { title: 'Top earners (all-time)' });

    const summary = await api('/api/admin/summary');
    if (summary.ok) {
      const rows = summary.monthly.map(m => ({
        label: m.label, shortLabel: shortMonthLabel(m.label), value: m.amount,
        sub: `${m.count} interviews`,
      }));
      renderTrendChart(adminTrendChart, rows, { title: 'Total paid per month' });
    }
  }

  // ── Admin: panelist roster (add / remove / restore) ──────────────────
  async function loadAdminPanelists() {
    showScreen(screenAdminPanelists);
    showLoading(panelistsTable);
    const data = await api('/api/admin/panelists');
    if (!data.ok) { showScreen(screenEmail); return; }
    allPanelists = data.panelists;
    panelistsSearch.value = '';
    renderPanelistsTable(allPanelists);

    const activeCount = allPanelists.filter(p => p.status !== 'removed').length;
    const removedCount = allPanelists.length - activeCount;
    panelistsSummary.textContent = `${activeCount} active panelist(s)`
      + (removedCount ? `, ${removedCount} removed` : '');
  }

  function renderPanelistsTable(list) {
    panelistsTable.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'admin-row admin-row-head panelist-row';
    header.innerHTML = ['Name', 'Email', 'Phone', 'Status', 'Total paid', '']
      .map(h => `<div>${escapeHtml(h)}</div>`).join('');
    panelistsTable.appendChild(header);

    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No panelists yet.';
      panelistsTable.appendChild(empty);
      return;
    }

    list.forEach(p => {
      const row = document.createElement('div');
      row.className = 'admin-row panelist-row';
      const badge = p.status === 'removed'
        ? '<span class="status-badge status-removed">Removed</span>'
        : p.is_manual
          ? '<span class="status-badge status-manual">Not yet paid</span>'
          : '<span class="status-badge status-active">Active</span>';
      row.innerHTML = `
        <div>${escapeHtml(p.name || '—')}</div>
        <div class="admin-email">${escapeHtml(p.email || '—')}</div>
        <div>${escapeHtml(p.phone || '—')}</div>
        <div>${badge}</div>
        <div class="admin-amount">${money(p.total_amount)}</div>
        <div class="panelist-actions"></div>
      `;
      const actionBtn = document.createElement('button');
      actionBtn.type = 'button';
      actionBtn.className = 'btn-link';
      actionBtn.textContent = p.status === 'removed' ? 'Restore' : 'Remove';
      actionBtn.addEventListener('click', () => handlePanelistAction(actionBtn, p));
      row.querySelector('.panelist-actions').appendChild(actionBtn);
      panelistsTable.appendChild(row);
    });
  }

  function handlePanelistAction(btn, p) {
    const removing = p.status !== 'removed';
    if (btn.dataset.confirming) {
      btn.disabled = true;
      api(`/api/admin/panelists/${encodeURIComponent(p.email)}/${removing ? 'remove' : 'restore'}`, {
        method: 'POST',
      }).then(() => loadAdminPanelists());
      return;
    }
    btn.dataset.confirming = '1';
    btn.textContent = removing ? 'Confirm remove?' : 'Confirm restore?';
    btn.classList.add('btn-link-confirm');
    setTimeout(() => {
      if (btn.dataset.confirming) {
        delete btn.dataset.confirming;
        btn.textContent = removing ? 'Remove' : 'Restore';
        btn.classList.remove('btn-link-confirm');
      }
    }, 3000);
  }

  panelistsSearch.addEventListener('input', () => {
    const q = panelistsSearch.value.trim().toLowerCase();
    const filtered = !q ? allPanelists : allPanelists.filter(p =>
      (p.name || '').toLowerCase().includes(q) ||
      (p.email || '').toLowerCase().includes(q) ||
      (p.phone || '').includes(q));
    renderPanelistsTable(filtered);
  });

  addPanelistForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = addPanelistForm.querySelector('button');
    btn.disabled = true;
    addPanelistMsg.textContent = '';
    addPanelistMsg.className = 'form-msg';
    try {
      const result = await api('/api/admin/panelists', {
        method: 'POST',
        body: JSON.stringify({
          name: document.getElementById('addPanelistName').value.trim(),
          email: document.getElementById('addPanelistEmail').value.trim(),
          phone: document.getElementById('addPanelistPhone').value.trim(),
        }),
      });
      if (result.ok) {
        addPanelistForm.reset();
        addPanelistMsg.textContent = 'Panelist added.';
        addPanelistMsg.className = 'form-msg success';
        allInterviewers = []; // force datalist/roster caches to refresh
        await loadAdminPanelists();
      } else {
        addPanelistMsg.textContent = result.error || 'Something went wrong.';
        addPanelistMsg.className = 'form-msg error';
      }
    } catch (err) {
      addPanelistMsg.textContent = 'Something went wrong. Try again.';
      addPanelistMsg.className = 'form-msg error';
    } finally {
      btn.disabled = false;
    }
  });

  function applyAdminSort() {
    const { key, dir } = adminSort;
    allInterviewers = allInterviewers.slice().sort((a, b) => {
      const av = a[key], bv = b[key];
      if (typeof av === 'string') return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });
  }

  function renderAdminTable(list) {
    adminTable.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'admin-row admin-row-head';
    const cols = [['name', 'Name'], ['email', 'Email'], ['total_count', 'Interviews'], ['total_amount', 'Total']];
    header.innerHTML = cols.map(([key, label]) => {
      const arrow = adminSort.key === key ? (adminSort.dir === 1 ? ' ▲' : ' ▼') : '';
      return `<div class="sortable" data-key="${key}">${label}${arrow}</div>`;
    }).join('');
    header.querySelectorAll('.sortable').forEach(el => {
      el.addEventListener('click', () => {
        const key = el.dataset.key;
        adminSort.dir = (adminSort.key === key) ? -adminSort.dir : 1;
        adminSort.key = key;
        applyAdminSort();
        const q = adminSearch.value.trim().toLowerCase();
        const filtered = !q ? allInterviewers : allInterviewers.filter(i =>
          i.name.toLowerCase().includes(q) || (i.email || '').toLowerCase().includes(q));
        renderAdminTable(filtered);
      });
    });
    adminTable.appendChild(header);

    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No matches.';
      adminTable.appendChild(empty);
      return;
    }

    list.forEach(i => {
      const row = document.createElement('div');
      row.className = 'admin-row';
      row.innerHTML = `
        <div>${escapeHtml(i.name)}</div>
        <div class="admin-email">${escapeHtml(i.email || '—')}</div>
        <div>${i.total_count}</div>
        <div class="admin-amount">${money(i.total_amount)}</div>
      `;
      row.addEventListener('click', () => loadAdminDetail(i));
      adminTable.appendChild(row);
    });
  }

  adminSearch.addEventListener('input', () => {
    const q = adminSearch.value.trim().toLowerCase();
    const filtered = !q ? allInterviewers : allInterviewers.filter(i =>
      i.name.toLowerCase().includes(q) || (i.email || '').toLowerCase().includes(q));
    renderAdminTable(filtered);
  });

  async function loadAdminDetail(interviewer) {
    showScreen(screenAdminDetail);
    resetSubTabs(ADMIN_DETAIL_SUBTABS);
    showLoading(adminDetailMonths);
    adminDetailStats.innerHTML = '';
    adminDetailName.textContent = interviewer.name;
    adminDetailBannerName.textContent = interviewer.name;
    const data = await api(`/api/admin/payouts/${encodeURIComponent(interviewer.db_id)}`);
    if (!data.ok) return;

    adminDetailName.textContent = data.name || interviewer.name;
    adminDetailBannerName.textContent = data.name || interviewer.name;
    const totalAmount = data.months.reduce((s, m) => s + m.amount, 0);
    const totalCount  = data.months.reduce((s, m) => s + m.count, 0);
    adminDetailSummary.textContent = data.months.length
      ? `${money(totalAmount)} total across ${totalCount} interviews, ${data.months.length} month(s)`
      : 'No payout history found for this person.';

    renderDashboardStats(adminDetailStats, data);
    renderTrendChart(adminDetailTrendChart, monthsToTrendRows(data.months), { title: 'Monthly earnings' });

    adminDetailMonths.innerHTML = '';
    if (!data.months.length) {
      adminDetailMonths.innerHTML = '<div class="empty-state">Nothing to show.</div>';
    } else {
      data.months.forEach(m => adminDetailMonths.appendChild(renderMonthCard(m, data.details[m.month] || [])));
    }
  }

  // ── Boot: check if already logged in ─────────────────────────────────
  (async function boot() {
    const me = await api('/api/me');
    if (me.ok) {
      isAdmin = !!me.is_admin;
      hasOwnPayouts = !!me.has_own_payouts;
      if (isAdmin) ensureInterviewersLoaded().then(populateInterviewerDatalist);
      if (hasOwnPayouts) {
        await loadDashboard();
      } else if (isAdmin) {
        await loadAdminList();
      } else {
        showScreen(screenEmail);
      }
    } else {
      showScreen(screenEmail);
    }
  })();
})();
