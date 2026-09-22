/* Shared rendering helpers (scoreBucket, atsBadgeHTML, scoreBadgeHTML,
   cleanSalaryText, cleanLocations) live in ui.js. Local aliases below keep
   this page working if ui.js failed to load — ui.js is the source of truth. */
const state = { jobs: [] };

function scoreBucketFn(score) {
  if (typeof scoreBucket === 'function') return scoreBucket(score);
  if (score == null || score === 0) return 'unscored';
  if (score >= 7) return 'high';
  if (score >= 4) return 'medium';
  return 'low';
}

function atsBadgeFn(job) {
  if (typeof atsBadgeHTML === 'function') return atsBadgeHTML(job);
  return atsBadge(job);
}

function atsBadge(job) {
  const usesAts = job ? job.uses_ats : null;
  const atsName = job && job.ats_name ? String(job.ats_name).trim() : '';
  const applyType = job && job.apply_type ? String(job.apply_type).trim() : '';
  const sig = job && job.ai_signal ? String(job.ai_signal).trim() : '';
  const aiTitle = sig
    ? "Employer's hiring process uses AI (" + escapeHTML(sig) + ")"
    : "Employer's hiring process uses AI";
  const ai = (job && job.uses_ai === true)
    ? `<span class="ats-badge ats-ai" title="${aiTitle}">🧠 AI hiring</span>`
    : '';
  if (usesAts === true) return `<span class="ats-badge ats-yes">🤖 ${escapeHTML(atsName ? `ATS · ${atsName}` : 'Uses ATS')}</span>${ai}`;
  if (usesAts === false) return `<span class="ats-badge ats-no">⚡ ${escapeHTML(applyType || 'Easy Apply')}</span>${ai}`;
  return `<span class="ats-badge ats-unknown">❔ ATS unknown</span>${ai}`;
}

function showNewBadgeToasts(badges, pointsEarned = 0) {
  badges.forEach((badge) => {
    const emoji = badge.emoji || '🏅';
    showToast(`${emoji} New badge: ${badge.name}`, 'success');
  });
  if (pointsEarned > 0) {
    showToast(`⚡ +${pointsEarned} XP`, 'success');
  }
  if (typeof window.refreshNavCounts === 'function') window.refreshNavCounts();
  if (typeof window.refreshBadgeCount === 'function') window.refreshBadgeCount();
}

const prefs = { sort: 'score', ats: '' };

function daysUntil(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return Math.round((d - Date.now()) / 86400000);
}

function applySortAndFilter() {
  let jobs = state.jobs.slice().filter((j) => !j.archived);
  if (prefs.ats === 'easy') jobs = jobs.filter((j) => j.uses_ats === false);
  else if (prefs.ats === 'ats') jobs = jobs.filter((j) => j.uses_ats === true);
  else if (prefs.ats === 'ai') jobs = jobs.filter((j) => j.uses_ai === true);
  switch (prefs.sort) {
    case 'deadline':
      jobs.sort((a, b) => {
        const da = daysUntil(a.application_deadline), db = daysUntil(b.application_deadline);
        if (da === null && db === null) return 0;
        if (da === null) return 1;
        if (db === null) return -1;
        return da - db;
      });
      break;
    case 'newest':
      jobs.sort((a, b) => String(b.date_found || '').localeCompare(String(a.date_found || '')));
      break;
    case 'company':
      jobs.sort((a, b) => String(a.company || '').localeCompare(String(b.company || '')));
      break;
    default:
      jobs.sort((a, b) => (b.relevance_score || 0) - (a.relevance_score || 0));
  }
  return jobs;
}

async function loadApplications() {
  const searchEl = document.getElementById('search-input');
  const search = searchEl ? searchEl.value.trim() : '';

  try {
    const res = await apiFetch(`/api/applications?q=${encodeURIComponent(search)}`);
    if (res === null) return; // redirected to login
    if (!res.ok) throw new Error('Failed to load applications');
    const data = await res.json();
    state.jobs = data.jobs || [];
    hideSkeleton(document.getElementById('app-skeleton'));
    renderRows();
  } catch (error) {
    hideSkeleton(document.getElementById('app-skeleton'));
    showToast(error.message, 'error');
  }
}

function renderRows() {
  const jobs = applySortAndFilter();
  const tbody = document.getElementById('applications-tbody');
  const empty = document.getElementById('applications-empty');
  const count = document.getElementById('app-count');
  if (count) count.textContent = String(state.jobs.length);

  if (!jobs.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    const tbl = tbody.closest('table');
    if (tbl) tbl.hidden = false;
    renderTop3();
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = jobs
    .map((job) => {
      const locations = (typeof cleanLocations === 'function' ? cleanLocations(job.locations) : (job.locations || []))
        .map(escapeHTML).join(', ') || '—';
      const rawLink = safeUrl(job.link);
      const link = rawLink
        ? `<button class="link-button" type="button" data-job-id="${job.id}">Open ↗</button>`
        : '<span class="text-muted">—</span>';
      const rawSalary = job.salary ? String(job.salary).trim() : '';
      const salaryRaw = (typeof cleanSalaryText === 'function') ? cleanSalaryText(rawSalary) : rawSalary;
      const salary = salaryRaw ? escapeHTML(salaryRaw) : '—';
      const rawScore = job.relevance_score;
      const hasScore = rawScore != null && rawScore > 0;
      const scoreCell = hasScore
        ? `<span class="score-badge score-${scoreBucketFn(rawScore)}">${escapeHTML(String(rawScore))}<span class="score-suffix">/10</span></span>`
        : `<span class="score-badge score-unscored" title="Not yet scored">—</span>`;
      const isPassed = job.passed_at != null && job.passed_at !== '';
      const passedFlag = isPassed
        ? `<span class="passed-chip" title="Link returned 404/410 on last check">⚠ expired</span>`
        : '';
      const rowClass = isPassed ? ' class="row-passed"' : '';
      const d = daysUntil(job.application_deadline);
      let deadlineHtml = '—';
      let deadlineClass = '';
      if (d !== null) {
        if (d < 0) { deadlineHtml = `overdue (${Math.abs(d)}d)`; deadlineClass = 'deadline-overdue'; }
        else if (d <= 2) { deadlineHtml = d === 0 ? 'today' : `${d}d`; deadlineClass = 'deadline-urgent'; }
        else if (d <= 7) { deadlineHtml = `in ${d}d`; deadlineClass = 'deadline-soon'; }
        else deadlineHtml = escapeHTML(job.application_deadline);
      }

      return `
        <tr data-job-id="${job.id}"${rowClass}>
          <td>${escapeHTML(job.title)} ${passedFlag}</td>
          <td>${escapeHTML(job.company)}</td>
          <td>${locations}</td>
          <td>${salary}</td>
          <td class="${deadlineClass}">${deadlineHtml}</td>
          <td>${scoreCell}</td>
          <td>${atsBadgeFn(job)}</td>
          <td>${link}</td>
        </tr>
      `;
    })
    .join('');

  empty.classList.add('hidden');

  renderTop3();
}

async function markExpired(jobId) {
  const button = document.querySelector(`.mark-expired[data-id="${jobId}"]`);
  if (!button) return;

  button.disabled = true;

  const res = await apiFetch(`/api/jobs/${jobId}/expired`, { method: 'POST' });
  if (res === null) return; // redirected to login
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    showToast(data.error || 'Could not mark as expired', 'error');
    button.disabled = false;
    return;
  }

  state.jobs = state.jobs.filter((job) => job.id !== jobId);
  renderRows();
  showToast('Job marked as Expired', 'info');
  if (Array.isArray(data.new_badges) && data.new_badges.length > 0) showNewBadgeToasts(data.new_badges);
}

document.getElementById('applications-tbody').addEventListener('click', (event) => {
  // "Open ↗" link: open the detail drawer, don't navigate to the job link.
  // (Clicking it would otherwise both open the link in a new tab and bubble
  // to the row handler, which would also open the drawer.)
  const openLink = event.target.closest('.link-button');
  if (openLink) {
    event.preventDefault();
    const row = openLink.closest('tr[data-job-id]');
    if (row) openDrawer(Number(row.dataset.jobId));
    return;
  }

  const applyButton = event.target.closest('.mark-applied');
  if (applyButton) {
    markApplied(Number(applyButton.dataset.id));
    return;
  }
  const expiredButton = event.target.closest('.mark-expired');
  if (expiredButton) {
    markExpired(Number(expiredButton.dataset.id));
    return;
  }
  // Row click (outside buttons) opens the detail drawer
  const row = event.target.closest('tr[data-job-id]');
  if (row) openDrawer(Number(row.dataset.jobId));
});

const _searchInput = document.getElementById('search-input');
if (_searchInput) {
  _searchInput.addEventListener('input', debounce(loadApplications, 200));
}

// Toolbar sort + ATS filter listeners
const _sortSelect = document.getElementById('sort-select');
const _atsFilter = document.getElementById('ats-filter');
if (_sortSelect) _sortSelect.addEventListener('change', (e) => { prefs.sort = e.target.value; renderRows(); });
if (_atsFilter) _atsFilter.addEventListener('change', (e) => { prefs.ats = e.target.value; renderRows(); });

// ── Top 3 today strip ───────────────────────────────────────────────────────
function renderTop3() {
  const strip = document.getElementById('top3-strip');
  const list = document.getElementById('top3-list');
  if (!strip || !list) return;

  // Top 3: score >= 7, Easy Apply (not ATS), not passed, oldest date_found first.
  const candidates = state.jobs
    .filter((j) => (j.relevance_score || 0) >= 7 && j.uses_ats !== true && !j.passed_at)
    .sort((a, b) => String(a.date_found || '').localeCompare(String(b.date_found || '')))
    .slice(0, 3);

  if (!candidates.length) { strip.classList.add('hidden'); return; }
  strip.classList.remove('hidden');
  list.innerHTML = candidates.map((j) => `
    <div class="top3-item">
      <span class="top3-score">${j.relevance_score || '—'}</span>
      <span class="top3-title">${escapeHTML(j.title)} <span class="text-muted">· ${escapeHTML(j.company)}</span></span>
      <span class="top3-ats">${atsBadgeFn(j)}</span>
      <button class="btn btn-primary btn--sm mark-applied" data-id="${j.id}">Apply</button>
    </div>
  `).join('');
}

// ── Cover letters (for modal dropdown) ──────────────────────────────────────
let _coverLetters = [];
async function loadCoverLetters() {
  try {
    const res = await apiFetch('/api/cover-letters');
    if (res === null) return;
    if (!res.ok) return;
    const data = await res.json();
    _coverLetters = data.cover_letters || [];
    const sel = document.getElementById('apply-cover');
    if (sel) {
      sel.innerHTML = '<option value="">None</option>' +
        _coverLetters.map((c) => `<option value="${escapeHTML(c.id)}">${escapeHTML(c.title)}</option>`).join('');
    }
  } catch (_) { /* optional feature — silently skip */ }
}

// ── Track options (drawer) ─────────────────────────────────────────────────
// Sourced from the user's tracks editor (/api/auth/tracks) instead of a
// hardcoded list, so renamed/added tracks show up everywhere. Fetched once
// per page load; the seeded names stay as first-paint fallback.
let _trackOptions = ['Software Engineer', 'Data Analyst', 'GIS/Spatial', 'Game Developer', 'ML/AI'];
let _trackOptionsLoaded = false;

async function ensureTrackOptions() {
  if (_trackOptionsLoaded) return;
  _trackOptionsLoaded = true;
  try {
    const res = await apiFetch('/api/auth/tracks');
    if (res && res.ok) {
      const data = await res.json();
      const names = (data.tracks || [])
        .filter((t) => t && t.name && t.name !== 'not a fit' && (t.enabled === undefined || t.enabled === 1 || t.enabled === true))
        .map((t) => t.name);
      if (names.length) _trackOptions = names;
    }
  } catch (_) { /* keep fallback list */ }
}

function fillDrawerTrackSelect(job) {
  const trackSel = document.getElementById('drawer-track');
  if (!trackSel) return;
  trackSel.innerHTML = '';
  [...new Set([..._trackOptions, 'not a fit', job.track].filter(Boolean))].forEach((t) => {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    if (t === job.track) opt.selected = true;
    trackSel.appendChild(opt);
  });
}

// ── Drawer ─────────────────────────────────────────────────────────────────
let _drawerJobId = null;
let _drawerSaveTimer = null;

function openDrawer(jobId) {
  const job = state.jobs.find((j) => j.id === jobId);
  if (!job) return;
  _drawerJobId = jobId;

  document.getElementById('drawer-job-title').textContent = job.title || '';
  document.getElementById('drawer-company').textContent = job.company || '';
  document.getElementById('drawer-location').textContent =
    (typeof cleanLocations === 'function' ? cleanLocations(job.locations) : (job.locations || [])).join(', ') || 'Location not listed';
  const rawSalary = job.salary ? String(job.salary).trim() : '';
  const salary = (typeof cleanSalaryText === 'function') ? cleanSalaryText(rawSalary) : rawSalary;
  document.getElementById('drawer-salary').textContent = salary ? `Salary: ${salary}` : '';
  document.getElementById('drawer-deadline').textContent = job.application_deadline
    ? `Deadline: ${job.application_deadline}`
    : '';

  // Badges
  const badgesEl = document.getElementById('drawer-badges');
  badgesEl.innerHTML = '';
  if (typeof scoreBadgeHTML === 'function') {
    const scoreWrap = document.createElement('div');
    scoreWrap.innerHTML = scoreBadgeHTML(job.relevance_score);
    badgesEl.appendChild(scoreWrap.firstElementChild);
  }
  const atsWrap = document.createElement('div');
  atsWrap.innerHTML = atsBadgeFn(job);
  badgesEl.appendChild(atsWrap.firstElementChild);

  // Link
  const linkEl = document.getElementById('drawer-link');
  const rawLink = safeUrl(job.link);
  if (rawLink) { linkEl.href = rawLink; linkEl.hidden = false; }
  else linkEl.hidden = true;

  // Notes (auto-save on debounce)
  const notesEl = document.getElementById('drawer-notes');
  notesEl.value = job.notes || '';
  notesEl.oninput = () => {
    clearTimeout(_drawerSaveTimer);
    _drawerSaveTimer = setTimeout(() => saveDrawerNotes(), 600);
  };

  // Deadline
  const deadlineEl = document.getElementById('drawer-deadline-input');
  deadlineEl.value = job.application_deadline || '';
  deadlineEl.onchange = () => saveDrawerDeadline();

  // Track — options come from the user's tracks editor (fetched once per page
  // load) so added/renamed tracks appear without code changes. 'not a fit'
  // and the job's current track are always offered.
  const trackSel = document.getElementById('drawer-track');
  fillDrawerTrackSelect(job);
  ensureTrackOptions().then(() => {
    if (_drawerJobId === job.id) fillDrawerTrackSelect(job); // repaint with fetched list
  });
  trackSel.onchange = () => saveDrawerTrack();

  // Description
  document.getElementById('drawer-description').textContent = job.description || 'No description provided.';

  // Archive button label
  const archiveBtn = document.getElementById('drawer-archive');
  archiveBtn.textContent = job.archived ? 'Unarchive' : 'Archive';

  // Show drawer
  document.getElementById('detail-drawer').classList.remove('hidden');
  document.getElementById('drawer-overlay').classList.remove('hidden');
}

function closeDrawer() {
  document.getElementById('detail-drawer').classList.add('hidden');
  document.getElementById('drawer-overlay').classList.add('hidden');
  _drawerJobId = null;
}

function saveDrawerNotes() {
  if (!_drawerJobId) return;
  const notes = document.getElementById('drawer-notes').value;
  const job = state.jobs.find((j) => j.id === _drawerJobId);
  if (job) job.notes = notes;
  apiFetch(`/api/jobs/${_drawerJobId}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notes }),
  }).catch(() => {});
}

function saveDrawerDeadline() {
  if (!_drawerJobId) return;
  const deadline = document.getElementById('drawer-deadline-input').value;
  const job = state.jobs.find((j) => j.id === _drawerJobId);
  if (job) job.application_deadline = deadline;
  apiFetch(`/api/jobs/${_drawerJobId}/deadline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ application_deadline: deadline }),
  }).then((res) => { if (res && res.ok) renderRows(); }).catch(() => {});
}

function saveDrawerTrack() {
  if (!_drawerJobId) return;
  const track = document.getElementById('drawer-track').value;
  const job = state.jobs.find((j) => j.id === _drawerJobId);
  if (job) job.track = track;
  apiFetch(`/api/jobs/${_drawerJobId}/reclassify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ track }),
  }).then((res) => { if (res && res.ok) showToast('Track updated', 'success'); }).catch(() => {});
}

// Wire drawer buttons once
document.getElementById('drawer-close').addEventListener('click', closeDrawer);
document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
document.getElementById('drawer-apply').addEventListener('click', () => { if (_drawerJobId) { closeDrawer(); openApplyModal(_drawerJobId); } });
document.getElementById('drawer-archive').addEventListener('click', async () => {
  if (!_drawerJobId) return;
  const job = state.jobs.find((j) => j.id === _drawerJobId);
  if (!job) return;
  const newVal = !job.archived;
  try {
    const res = await apiFetch(`/api/jobs/${_drawerJobId}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archived: newVal }),
    });
    if (res && res.ok) {
      job.archived = newVal;
      showToast(newVal ? 'Archived' : 'Unarchived', 'success');
      closeDrawer();
      renderRows();
      return;
    }
    const data = await res.json().catch(() => ({}));
    showToast(data.error || 'Could not archive job', 'error');
  } catch (err) {
    showToast('Could not archive job: ' + err.message, 'error');
  }
});

// ── Mark-Applied modal ──────────────────────────────────────────────────────
let _modalJobId = null;
function openApplyModal(jobId) {
  const job = state.jobs.find((j) => j.id === jobId);
  if (!job) return;
  _modalJobId = jobId;
  const modal = document.getElementById('apply-modal');
  document.getElementById('apply-job-title').textContent = `${job.title} · ${job.company}`;
  document.getElementById('apply-resume').value = '';
  document.getElementById('apply-notes').value = '';
  const dateEl = document.getElementById('apply-date');
  if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
  modal.classList.remove('hidden');
  document.getElementById('apply-resume').focus();
}
function closeApplyModal() {
  document.getElementById('apply-modal').classList.add('hidden');
  _modalJobId = null;
}

const _applyCancel = document.getElementById('apply-cancel');
const _applySkip = document.getElementById('apply-skip');
const _applyConfirm = document.getElementById('apply-confirm');
if (_applyCancel) _applyCancel.addEventListener('click', closeApplyModal);
if (_applySkip) _applySkip.addEventListener('click', () => { if (_modalJobId) quickMarkApplied(_modalJobId); closeApplyModal(); });
if (_applyConfirm) _applyConfirm.addEventListener('click', () => {
  if (!_modalJobId) return;
  const resume = document.getElementById('apply-resume').value.trim();
  const cover = document.getElementById('apply-cover').value;
  const notes = document.getElementById('apply-notes').value.trim();
  quickMarkApplied(_modalJobId, { resume, cover, notes });
  closeApplyModal();
});

async function quickMarkApplied(jobId, extras = {}) {
  const button = document.querySelector(`.mark-applied[data-id="${jobId}"]`);
  if (button) { button.disabled = true; button.textContent = 'Applying…'; }

  const body = { applied_at: new Date().toISOString().slice(0, 10) };
  if (extras.resume) body.submitted_resume = extras.resume;
  if (extras.cover) body.submitted_cover_letter = extras.cover;
  if (extras.notes) body.notes = extras.notes;

  const res = await apiFetch(`/api/jobs/${jobId}/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res === null) return;
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    showToast(data.error || 'Could not mark as applied', 'error');
    if (button) { button.disabled = false; button.textContent = 'Apply'; }
    return;
  }

  state.jobs = state.jobs.filter((job) => job.id !== jobId);
  renderRows();
  renderTop3();
  showToast('Job marked as Applied', 'success');
  if (Array.isArray(data.new_badges) && data.new_badges.length > 0) {
    showNewBadgeToasts(data.new_badges, data.points_earned);
  } else if (data.points_earned > 0) {
    showToast(`⚡ +${data.points_earned} XP`, 'success');
  }
}

// Close modal on overlay click
const _applyModal = document.getElementById('apply-modal');
if (_applyModal) {
  _applyModal.addEventListener('click', (e) => { if (e.target === _applyModal) closeApplyModal(); });
}

// ── Wire up table row clicks to open modal ──────────────────────────────────
document.getElementById('applications-tbody').addEventListener('click', (event) => {
  const applyButton = event.target.closest('.mark-applied');
  if (applyButton) {
    openApplyModal(Number(applyButton.dataset.id));
    return;
  }
  const expiredButton = event.target.closest('.mark-expired');
  if (expiredButton) markExpired(Number(expiredButton.dataset.id));
});

loadCoverLetters();
loadApplications();