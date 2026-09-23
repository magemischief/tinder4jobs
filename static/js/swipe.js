const state = {
  queue: [],
  current: null,
  busy: false,
  filters: {
    location: '',
    job_type: '',
    score: '',
    ats: '',
  },
  trackOptions: [],
  energyMax: 0,
  energyAcknowledged: false,
  dailyTotal: 0,
  dailyGoal: 10,
  totalPoints: 0,
  history: [],
  historyLimit: 20,
  streak: 0,
  badgeCount: 0,
  // Track last touch position for swipe gestures
  lastTouchX: null,
  lastTouchY: null,
  // Touch drag state for animated swipe
  touchStartX: 0,
  touchStartY: 0,
  touchCurrentX: 0,
  touchActive: false,
};
// Helper: escape HTML for safe inclusion in HTML context
function escapeHTML(str) {
  if (typeof str !== 'string') return str;
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}


function getFilterValues() {
  return {
    location: document.getElementById('location-filter')?.value || '',
    job_type: document.getElementById('job-type-filter')?.value || '',
    score: document.getElementById('score-filter')?.value || '',
    ats: document.getElementById('ats-filter')?.value || '',
  };
}

/* Shared rendering helpers now live in ui.js (scoreBucket, atsBadgeHTML,
   scoreBadgeHTML, cleanSalaryText, cleanLocations, deadlinePillHTML). The
   local wrappers below only apply when ui.js failed to load (cached old
   base.html) — they are NOT the source of truth. */
if (typeof scoreBucket === 'undefined') {
  var scoreBucket = function (score) {
    if (score == null || score === 0) return 'unscored';
    if (score >= 7) return 'high';
    if (score >= 4) return 'medium';
    return 'low';
  };
}
if (typeof atsBadge === 'undefined') {
  var atsBadge = function (job) {
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
  };
}

if (typeof deadlinePillHTML === 'undefined') {
  var deadlinePillHTML = function (deadline) {
    if (!deadline) return '';
    return `<p class="card-deadline">Apply by ${escapeHTML(deadline)}</p>`;
  };
}
function deadlinePillHtml(deadline) {
  return deadlinePillHTML(deadline);
}

function applyScoreFilter(jobs) {
  const bucket = state.filters.score;
  if (!bucket) return jobs;
  const fn = (typeof scoreBucket === 'function') ? scoreBucket : (s) => {
    if (s == null || s === 0) return 'unscored';
    if (s >= 7) return 'high';
    if (s >= 4) return 'medium';
    return 'low';
  };
  return jobs.filter((job) => fn(job.relevance_score) === bucket);
}

/* Apply-type filter (client-side, like the score filter): '' | 'easy' | 'ats' | 'ai'. */
function applyAtsFilter(jobs) {
  const mode = state.filters.ats;
  if (!mode) return jobs;
  if (mode === 'easy') return jobs.filter((j) => j.uses_ats === false);
  if (mode === 'ats') return jobs.filter((j) => j.uses_ats === true);
  if (mode === 'ai') return jobs.filter((j) => j.uses_ai === true);
  return jobs;
}

function updateCount() {
  const el = document.getElementById('queue-count');
  if (el) el.textContent = String(state.queue.length);
  const mobileEl = document.getElementById('mobile-queue-count');
  if (mobileEl) mobileEl.textContent = String(state.queue.length);
}

function updateSwipeActionState() {
  const canSwipe = Boolean(state.current) && !state.busy;
  ['superdislike-btn', 'dislike-btn', 'unsure-btn', 'like-btn'].forEach((id) => {
    const button = document.getElementById(id);
    if (!button) return;
    if (!button.dataset.defaultTitle) button.dataset.defaultTitle = button.title;
    button.disabled = !canSwipe;
    button.setAttribute('aria-disabled', String(!canSwipe));
    button.title = canSwipe ? button.dataset.defaultTitle : 'No job in the queue';
  });
}

function updateProgress() {
  const todayEl = document.getElementById('progress-today');
  const goalEl = document.getElementById('progress-goal-num');
  const barEl = document.getElementById('progress-bar');
  const streakEl = document.getElementById('progress-streak');
  const badgesEl = document.getElementById('progress-badges');
  const pointsEl = document.getElementById('progress-points');
  if (todayEl) todayEl.textContent = String(state.dailyTotal);
  if (goalEl) goalEl.textContent = String(state.dailyGoal);
  if (barEl) {
    const pct = state.dailyGoal > 0 ? Math.min(100, (state.dailyTotal / state.dailyGoal) * 100) : 0;
    barEl.style.width = pct + '%';
  }
  if (streakEl) streakEl.textContent = String(state.streak);
  if (badgesEl) badgesEl.textContent = String(state.badgeCount);
  if (pointsEl) pointsEl.textContent = String(state.totalPoints || 0);
}

const TRACK_THEME = {
  'Software Engineer': {
    accent: '#3b82f6',
    soft: 'rgba(59, 130, 246, 0.16)',
    glow: 'rgba(59, 130, 246, 0.22)',
  },
  'Data Analyst': {
    accent: '#10b981',
    soft: 'rgba(16, 185, 129, 0.16)',
    glow: 'rgba(16, 185, 129, 0.22)',
  },
  'GIS/Spatial': {
    accent: '#06b6d4',
    soft: 'rgba(6, 182, 212, 0.16)',
    glow: 'rgba(6, 182, 212, 0.22)',
  },
  'Game Developer': {
    accent: '#a855f7',
    soft: 'rgba(168, 85, 247, 0.16)',
    glow: 'rgba(168, 85, 247, 0.22)',
  },
  'ML/AI': {
    accent: '#f97316',
    soft: 'rgba(249, 115, 22, 0.16)',
    glow: 'rgba(249, 115, 22, 0.22)',
  },
  engineering: { accent: '#3b82f6', soft: 'rgba(59, 130, 246, 0.16)', glow: 'rgba(59, 130, 246, 0.22)' },
  data: { accent: '#10b981', soft: 'rgba(16, 185, 129, 0.16)', glow: 'rgba(16, 185, 129, 0.22)' },
  design: { accent: '#ec4899', soft: 'rgba(236, 72, 153, 0.16)', glow: 'rgba(236, 72, 153, 0.22)' },
  product: { accent: '#8b5cf6', soft: 'rgba(139, 92, 246, 0.16)', glow: 'rgba(139, 92, 246, 0.22)' },
  marketing: { accent: '#f97316', soft: 'rgba(249, 115, 22, 0.16)', glow: 'rgba(249, 115, 22, 0.22)' },
  sales: { accent: '#ef4444', soft: 'rgba(239, 68, 68, 0.16)', glow: 'rgba(239, 68, 68, 0.22)' },
  operations: { accent: '#14b8a6', soft: 'rgba(20, 184, 166, 0.16)', glow: 'rgba(20, 184, 166, 0.22)' },
  finance: { accent: '#eab308', soft: 'rgba(234, 179, 8, 0.16)', glow: 'rgba(234, 179, 8, 0.22)' },
  'not a fit': {
    accent: '#64748b',
    soft: 'rgba(100, 116, 139, 0.16)',
    glow: 'rgba(100, 116, 139, 0.18)',
  },
};

// Static palette above is only the first-paint fallback. The review page
// fetches the user's actual track colors (`getTrackColorMap`) so an edited
// color in the tracks editor recolors swipe cards on the next queue load.
var TRACK_COLOR_OVERRIDES = {};

function hexToRgba(hex, alpha) {
  var m = /^#([0-9a-fA-F]{6})$/.exec((hex || '').trim());
  if (!m) return null;
  var r = parseInt(m[1].slice(0, 2), 16);
  var g = parseInt(m[1].slice(2, 4), 16);
  var b = parseInt(m[1].slice(4, 6), 16);
  return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
}

function themeFromAccent(accent) {
  var fallback = TRACK_THEME['not a fit'];
  var hex = /^#[0-9a-fA-F]{6}$/.test((accent || '').trim()) ? accent.trim() : null;
  if (!hex) return { accent: fallback.accent, soft: fallback.soft, glow: fallback.glow };
  return {
    accent: hex,
    soft: hexToRgba(hex, 0.16) || fallback.soft,
    glow: hexToRgba(hex, 0.18) || fallback.glow,
  };
}

function getTrackColorMap() {
  return TRACK_COLOR_OVERRIDES;
}

function getTrackTheme(track) {
  const key = (track || '').trim();
  const override = TRACK_COLOR_OVERRIDES[key];
  // Case-insensitive match so a renamed track still picks up its color.
  if (!override) {
    const lower = key.toLowerCase();
    for (const name of Object.keys(TRACK_COLOR_OVERRIDES)) {
      if (name.toLowerCase() === lower) return themeFromAccent(TRACK_COLOR_OVERRIDES[name]);
    }
  } else {
    return themeFromAccent(override);
  }
  const paletteKey = Object.keys(TRACK_THEME).find((name) => name.toLowerCase() === key.toLowerCase());
  return (paletteKey && TRACK_THEME[paletteKey]) || {
    accent: '#4f46e5',
    soft: 'rgba(79, 70, 229, 0.16)',
    glow: 'rgba(79, 70, 229, 0.18)',
  };
}

function applyTrackTheme(card, track) {
  if (!card) return;
  const { accent, soft, glow } = getTrackTheme(track);
  card.style.setProperty('--job-accent', accent);
  card.style.setProperty('--job-accent-soft', soft);
  card.style.setProperty('--job-accent-glow', glow);
}

function populateFilterOptions(options = { locations: [], job_types: [] }) {
  const locSel = document.getElementById('location-filter');
  const typeSel = document.getElementById('job-type-filter');
  if (locSel) {
    const current = locSel.value;
    locSel.innerHTML = '<option value="">All locations</option>' +
      (options.locations || []).map(l =>
        `<option value="${escapeHTML(l)}"${l === current ? ' selected' : ''}>${escapeHTML(l)}</option>`
      ).join('');
  }
  if (typeSel) {
    const current = typeSel.value;
    typeSel.innerHTML = '<option value="">All job types</option>' +
      (options.job_types || []).map(t =>
        `<option value="${escapeHTML(t)}"${t === current ? ' selected' : ''}>${escapeHTML(t)}</option>`
      ).join('');
  }
  if (Array.isArray(options.job_types)) {
    state.trackOptions = options.job_types;
  }
}

function renderCard() {
  const container = document.getElementById('card-container');

  if (!state.queue.length) {
    container.innerHTML = '';
    state.current = null;
    updateSwipeActionState();
    updateUndoButtonState();
    updateCount();
    return;
  }

  const job = state.queue[0];
  state.current = job;
  updateSwipeActionState();

  // Dedupe locations case-insensitively so a polluted DB cannot render the same
  // city ten times in a row (defense-in-depth for legacy rows).
  // Shared helper in ui.js, with inline fallback for cached old base.html.
  const cleanList = (typeof cleanLocations === 'function')
    ? cleanLocations(job.locations)
    : (() => {
      const seen = new Set();
      const out = [];
      (job.locations || []).forEach((loc) => {
        const v = (loc == null ? '' : String(loc).trim());
        const k = v.toLowerCase();
        if (v && k !== 'none' && !seen.has(k)) { seen.add(k); out.push(v); }
      });
      return out;
    })();
  const locationsText = cleanList.length
    ? cleanList.map(escapeHTML).join(' · ')
    : 'Location not listed';
  const locations = escapeHTML(locationsText);
  const description = escapeHTML(job.description || 'No description provided.');
  const status = escapeHTML(job.status || 'Review to Apply');
  const rawLink = safeUrl(job.link);
  const linkHtml = rawLink
    ? `<a class="card-link" href="${escapeHTML(rawLink)}" target="_blank" rel="noopener noreferrer">View original posting →</a>`
    : '';

  // Relevance score badge (1–10) — daemon populates relevance_score via Ollama.
  // Shared helper in ui.js with inline fallback.
  const rawScore = job.relevance_score;
  const hasScore = rawScore != null && rawScore > 0;
  const scoreBadgeHtml = (typeof scoreBadgeHTML === 'function')
    ? scoreBadgeHTML(rawScore)
    : (hasScore
      ? `<span class="score-badge score-${scoreBucket(rawScore)}" title="AI relevance score">${escapeHTML(String(rawScore))}<span class="score-suffix">/10</span></span>`
      : `<span class="score-badge score-unscored" title="Not yet scored">—</span>`);

  const atsBadgeHtml = (typeof atsBadgeHTML === 'function') ? atsBadgeHTML(job) : atsBadge(job);

  // "Passed" overlay — listing is dead (404/410) per passed_checker.
  const isPassed = job.passed_at != null && job.passed_at !== '';
  const passedOverlayHtml = isPassed
    ? `<div class="passed-overlay" title="Link returned 404/410 on last check"><span class="passed-icon">⚠</span><span class="passed-text">Listing expired</span></div>`
    : '';

  const availableTracks = [...new Set([
    'not a fit',
    ...(state.trackOptions || []),
    job.track,
  ].filter(Boolean))].filter((value) => value && value.trim() !== '');
  const trackOptionsMarkup = availableTracks.map((value) => {
    const safeValue = escapeHTML(value);
    return `<option value="${safeValue}"${value === job.track ? ' selected' : ''}>${safeValue}</option>`;
  }).join('');

  // Salary guard: legacy rows can hold junk like "None-None None" — hide it.
  // Shared cleanSalaryText() in ui.js, inline fallback for old cached pages.
  const rawSalary = job.salary ? String(job.salary).trim() : '';
  const salaryClean = (typeof cleanSalaryText === 'function')
    ? cleanSalaryText(rawSalary) : (rawSalary && !/none|nan/i.test(rawSalary) && !/^\W*$/.test(rawSalary))
      ? rawSalary : '';
  const salaryCleanHtml = salaryClean ? escapeHTML(salaryClean) : '';

  container.innerHTML = `
    <article class="job-card enter${isPassed ? ' job-card-passed' : ''}" data-job-id="${job.id}">
      ${passedOverlayHtml}
      <div class="card-top">
        <span class="badge">${status}</span>
        <span class="card-top-badges">${atsBadgeHtml}${scoreBadgeHtml}</span>
      </div>
      <div class="card-body">
        <h2>${escapeHTML(job.title)}</h2>
        <h3 class="card-company">${escapeHTML(job.company)}</h3>
        <p class="card-location">${locations}</p>
        ${salaryCleanHtml ? `<p class="card-salary">${salaryCleanHtml}</p>` : ''}
        ${(job.salary_min || job.salary_max) ? `<p class="card-salary">${escapeHTML(formatSalary(job.salary_min, job.salary_max, job.salary_currency))}</p>` : ''}
        ${deadlinePillHtml(job.application_deadline)}
        ${linkHtml}
        <div class="card-description" tabindex="0">${description}</div>
        <div class="card-dates">
          ${job.applied_at ? `<span class="date-pill">Applied ${escapeHTML(job.applied_at)}</span>` : ''}
          ${job.interview_at ? `<span class="date-pill">Interview ${escapeHTML(job.interview_at)}</span>` : ''}
        </div>
        <div class="card-extras">
          <details class="card-extras-panel">
            <summary>
              <span>More options</span>
              <span class="track-pill">${escapeHTML(job.track || 'untracked')}</span>${job.date_found ? `<span class="card-meta-dot">·</span><span class="text-muted">${escapeHTML(job.date_found)}</span>` : ''}
            </summary>
            <div class="card-extras-body">
              <div class="card-reclassify">
                <label for="track-reclassify">Track</label>
                <select id="track-reclassify" class="track-select" data-id="${job.id}">
                  ${trackOptionsMarkup}
                </select>
              </div>
              <div class="card-notes">
                <label for="job-notes-${job.id}">Notes</label>
                <textarea id="job-notes-${job.id}" class="job-notes" rows="3" data-id="${job.id}" placeholder="Why this is interesting, who to contact, etc.">${escapeHTML(job.notes || '')}</textarea>
                <span class="notes-status text-muted" data-status-for="${job.id}" aria-live="polite"></span>
              </div>
              <div class="card-secondary-actions">
                <button type="button" class="btn btn-secondary btn--sm js-archive" data-id="${job.id}">${job.archived ? 'Unarchive' : 'Archive'}</button>
              </div>
            </div>
          </details>
        </div>
      </div>
      <div class="card-duplicates" id="card-duplicates-${job.id}"></div>
    </article>
  `;

  const card = container.querySelector('.job-card');
  applyTrackTheme(card, job.track || '');

  // Auto-save track on change (no separate Save button)
  const trackSelect = container.querySelector('#track-reclassify');
  if (trackSelect) {
    trackSelect.addEventListener('change', async () => {
      const selectedTrack = trackSelect.value.trim();
      if (!selectedTrack || selectedTrack === job.track) return;
      try {
        const response = await fetch(`/api/jobs/${job.id}/reclassify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track: selectedTrack }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Could not update track');
        showToast(`Track set to ${selectedTrack}`, 'success');
        if (state.current) state.current.track = selectedTrack;
        if (state.queue[0]) state.queue[0].track = selectedTrack;
        await loadFilterOptions();
  } catch (error) {
        showToast(error.message, 'error');
      }
    });
  }

  // Auto-save notes on input / blur (no separate Save button)
  const notesEl = container.querySelector('.job-notes');
  const statusEl = container.querySelector('[data-status-for]');
  if (notesEl) {
    const saveNotes = debounce(async () => {
      if (!state.current || String(state.current.id) !== String(job.id)) return;
      try {
        const r = await fetch(`/api/jobs/${job.id}/notes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes: notesEl.value }),
        });
        if (!r.ok) throw new Error('save failed');
        if (state.current) state.current.notes = notesEl.value;
        if (statusEl) {
          statusEl.textContent = 'Saved';
          setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 1500);
        }
      } catch (e) {
        if (statusEl) statusEl.textContent = 'Save failed';
        showToast(e.message, 'error');
      }
    }, 400);
    notesEl.addEventListener('input', saveNotes);
    notesEl.addEventListener('blur', saveNotes);
  }

  // Archive / Unarchive — toggles the job's archived flag and removes it from
  // the review queue (archived jobs are filtered out of the queue on reload).
  const archiveBtn = container.querySelector('.js-archive');
  if (archiveBtn) {
    archiveBtn.addEventListener('click', async () => {
      if (!state.current || String(state.current.id) !== String(job.id)) return;
      try {
        const response = await fetch(`/api/jobs/${job.id}/archive`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archived: !job.archived }),
        });
        if (!response.ok) throw new Error('Archive failed');
        state.queue.shift();
        await animateCardExit('right');
    renderCard();
        updateCount();
        refreshGoalProgress();
        showToast(job.archived ? 'Unarchived' : 'Archived', 'info');
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  // Load duplicate candidates for the current card
  loadDuplicateCandidates(job);
  updateUndoButtonState();
  updateCount();
}

function animateCardExit(direction) {
  const card = document.querySelector('.job-card');
  if (!card) return Promise.resolve();
  const exitClass = `exit-${direction}`;
  card.classList.add(exitClass);
  return new Promise((resolve) => {
    const onDone = () => { card.removeEventListener('transitionend', onDone); resolve(); };
    card.addEventListener('transitionend', onDone);
    setTimeout(() => {
      card.classList.remove(exitClass);
      resolve();
    }, 420);
  });
}

async function undoLast() {
  if (state.busy || !state.history.length) return;
  const entry = state.history.pop();
  updateUndoButtonState();
  try {
    state.busy = true;
    const res = await fetch(`/api/jobs/${entry.job.id}/revert`, { method: 'POST' });
    if (!res.ok) throw new Error('Revert failed');
    state.queue.unshift(entry.job);
    renderCard();
    showToast(`Undid ${entry.action} — ${entry.job.title}`, 'success');
  } catch (err) {
    state.history.push(entry); // re-push on failure
    updateUndoButtonState();
    showToast(err.message, 'error');
  } finally {
    state.busy = false;
    updateSwipeActionState();
  }
}

async function handleDuplicate() {
  if (state.busy || !state.current) return;
  state.busy = true;

  const job = state.current;

  try {
    const response = await fetch(`/api/jobs/${job.id}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      showToast(data.error || "Could not mark as duplicate", "error");
      state.busy = false;
      return;
    }

    const result = data.result || {};
    state.queue.shift();
    await animateCardExit("right");
    renderCard();
    updateCount();
    refreshGoalProgress();

    if (result.merged) {
      showToast(`Merged – kept job #${result.kept_job_id}`, "success");
    } else {
      showToast("Marked as duplicate", "info");
    }

    // Surface newly-earned badges
    if (Array.isArray(data.new_badges) && data.new_badges.length > 0) {
      showNewBadgeToasts(data.new_badges);
    }
  } catch (err) {
    showToast("Network error – could not mark as duplicate", "error");
  } finally {
    state.busy = false;
  }
}

async function handleAction(action) {
  if (state.busy || !state.current) return;
  // Energy soft-block: hitting the daily review cap pauses actions until the
  // user acknowledges the warning (they can then keep going).
  if (state.energyMax > 0 && state.dailyTotal >= state.energyMax && !state.energyAcknowledged) {
    checkEnergyWarning();
    return;
  }
  // 'interested' = like, 'not-interested' = dislike (semantic aliases)
  if (action === 'interested') action = 'like';
  if (action === 'not-interested') action = 'dislike';

  state.busy = true;
  updateSwipeActionState();

  const job = state.current;
  const wasLast = state.queue.length <= 1;

  let response;
  let data = {};
  try {
    response = await fetch(`/api/jobs/${job.id}/swipe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    data = await response.json().catch(() => ({}));
  } catch (error) {
    showToast('Network error – could not update job', 'error');
    state.busy = false;
    updateSwipeActionState();
    return;
  }

  if (!response.ok) {
    showToast(data.error || 'Could not update job', 'error');
    state.busy = false;
    updateSwipeActionState();
    return;
  }

  pushHistory(job, action);
  state.queue.shift();
  const direction = action === 'like' ? 'right' : (action === 'dislike' || action === 'superdislike') ? 'left' : 'unsure';
  // Haptic tick on supported devices (no-op elsewhere; ignored on desktop).
  try { navigator.vibrate?.(10); } catch (e) { /* unsupported */ }
  await animateCardExit(direction);
  renderCard();
  state.busy = false;
  updateSwipeActionState();
  updateUndoButtonState();

  // Refresh today's counts (goal progress / energy guard) after the action.
  refreshGoalProgress();

  // Surface newly-earned badges (if any) via toast + nav refresh
  if (Array.isArray(data.new_badges) && data.new_badges.length > 0) {
    showNewBadgeToasts(data.new_badges);
  }

  if (action === 'unsure' && wasLast) {
    showToast('Only one card remains. Use Like or Dislike to resolve it.', 'warning');
  }
}

// Pop a toast for each new badge and refresh the global badge/notification counts.
function showNewBadgeToasts(badges) {
  badges.forEach((badge) => {
    const emoji = badge.emoji || '🏅';
    showToast(`${emoji} New badge: ${badge.name}`, 'success');
  });
  // Ask the global counters to refresh themselves
  if (typeof window.refreshNavCounts === 'function') {
    window.refreshNavCounts();
  }
  if (typeof window.refreshBadgeCount === 'function') {
    window.refreshBadgeCount();
  }
}

async function loadFilterOptions() {
  // Populate location/job-type dropdowns and track colors from /api/review/filter-options.
  try {
    const response = await fetch('/api/review/filter-options');
    if (!response.ok) return;
    const options = await response.json();
    // Populate dropdowns (and state.trackOptions) before any card re-render so
    // the reclassification select can offer every enabled editor track.
    populateFilterOptions(options || {});
    if (options && options.track_colors && typeof options.track_colors === 'object') {
      TRACK_COLOR_OVERRIDES = options.track_colors;
    }
    // Re-render the live card so it picks up both the full track list and the
    // freshly loaded track colors.
    if (state.current) renderCard();
  } catch (error) {
    console.error('Could not load filter options:', error);
  }
}

async function loadQueue() {
  state.busy = true;
  state.current = null;
  updateSwipeActionState();
  state.filters = getFilterValues();

  const params = new URLSearchParams();
  if (state.filters.location) params.set('location', state.filters.location);
  if (state.filters.job_type) params.set('job_type', state.filters.job_type);

  try {
    const response = await fetch(`/api/review/queue?${params.toString()}`);
    if (!response.ok) throw new Error('Failed to load queue');
    const data = await response.json();
    state.queue = applyAtsFilter(applyScoreFilter(data.jobs || []));
    state.current = null;

    // Crossfade the skeleton out before rendering the real card
    const skeleton = document.getElementById('card-skeleton');
    if (skeleton) {
      skeleton.classList.add('skeleton-fade-out');
      setTimeout(() => renderCard(), 300); // match the animation duration
    } else {
      renderCard();
    }
  } catch (error) {
    document.getElementById('card-container').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <h2>Could not load the queue</h2>
        <p>${escapeHTML(error.message)}</p>
      </div>
    `;
    hideSkeleton(document.getElementById('card-skeleton'));
  } finally {
    state.busy = false;
    updateSwipeActionState();
  }
}

// When filters change, reload the queue
function bindFilterChanges() {
  const filters = ['location-filter', 'job-type-filter', 'score-filter', 'ats-filter'];
  filters.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      state.filters = getFilterValues();
      loadQueue();
      setMobileFiltersOpen(false);
    });
  });
}

function setMobileFiltersOpen(open) {
  const page = document.querySelector('.swipe-page');
  const toggle = document.getElementById('mobile-filter-toggle');
  if (!page || !toggle) return;
  page.classList.toggle('mobile-filters-open', open);
  toggle.setAttribute('aria-expanded', String(open));
}

function bindMobileFilterPopover() {
  const toggle = document.getElementById('mobile-filter-toggle');
  const filters = document.getElementById('swipe-filters');
  if (!toggle || !filters) return;
  toggle.addEventListener('click', () => {
    setMobileFiltersOpen(!document.querySelector('.swipe-page')?.classList.contains('mobile-filters-open'));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMobileFiltersOpen(false);
  });
  document.addEventListener('pointerdown', (event) => {
    if (window.matchMedia('(max-width: 768px)').matches &&
        !filters.contains(event.target) && !toggle.contains(event.target)) {
      setMobileFiltersOpen(false);
    }
  });
}


function formatSalary(min, max, currency) {
  const cur = currency || '$';
  if (min && max) return cur + Number(min).toLocaleString() + ' – ' + cur + Number(max).toLocaleString();
  if (min) return 'From ' + cur + Number(min).toLocaleString();
  if (max) return 'Up to ' + cur + Number(max).toLocaleString();
  return '';
}

async function archiveCurrent(jobId) {
  const card = document.querySelector('.job-card');
  if (!card) return;
  const btn = card.querySelector('.js-archive');
  const newVal = !(state.current && state.current.archived);
  try {
    const r = await fetch('/api/jobs/' + jobId + '/archive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archived: newVal }),
    });
    if (!r.ok) throw new Error('archive failed');
    if (state.current) state.current.archived = newVal;
    if (btn) btn.textContent = newVal ? 'Unarchive' : 'Archive';
    showToast(newVal ? 'Archived' : 'Unarchived', 'success');
  } catch (e) { showToast(e.message, 'error'); }
}


// Load duplicate candidates for a job and render them below the card
async function loadDuplicateCandidates(job) {
  if (!job) return;
  const container = document.getElementById('card-duplicates-' + job.id);
  if (!container) return;

  try {
    const r = await fetch('/api/jobs/' + job.id + '/duplicate-candidates');
    if (!r.ok) return;
    const data = await r.json();
    if (!data.candidates || data.candidates.length === 0) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `
      <div class="duplicates-panel">
        <div class="duplicates-header">
          <span class="duplicates-label">Possible duplicates (${data.count})</span>
        </div>
        <div class="duplicates-list">
          ${data.candidates.map(c => `
            <div class="duplicate-chip">
              <span class="dup-title">${escapeHTML(c.title)}</span>
              <span class="dup-company">@ ${escapeHTML(c.company)}</span>
              <span class="dup-score">${c.relevance_score ? c.relevance_score + '/10' : '—'}</span>
              <button class="dup-merge-btn" data-target="${c.id}" title="Merge into job #${c.id}">Merge</button>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    container.querySelectorAll('.dup-merge-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const targetId = parseInt(btn.dataset.target);
        try {
          const res = await fetch('/api/jobs/' + job.id + '/duplicate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ other_job_id: targetId }),
          });
          const d = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(d.error || 'Merge failed');
          showToast(d.result && d.result.merged ? `Merged into job #${d.result.kept_job_id}` : 'Marked as duplicate', 'success');
          state.queue.shift();
          await animateCardExit('right');
          renderCard();
          updateCount();
          refreshGoalProgress();
        } catch (err) {
          showToast(err.message, 'error');
        }
      });
    });
  } catch (e) {
    // silently fail
  }
}


function bindCardButtons() {
  const container = document.getElementById('card-container');
  if (!container) return;
  container.addEventListener('click', (e) => {
    const archBtn = e.target.closest('.js-archive');
    if (archBtn) { e.preventDefault(); archiveCurrent(archBtn.dataset.id); }
  });
}

function bindCardDrag() {
  const container = document.getElementById('card-container');
  if (!container) return;

  let startX = 0, startY = 0, dx = 0, dy = 0;
  let active = false;
  let card = null;
  let lastX = 0, lastY = 0, lastT = 0;
  let velX = 0, velY = 0;

  function showStamp(action) {
    document.querySelectorAll('.swipe-stamp').forEach((el) => {
      el.classList.toggle('swipe-stamp--visible', el.classList.contains(`swipe-stamp--${action}`));
    });
  }

  function clearStamp() {
    document.querySelectorAll('.swipe-stamp').forEach((el) => {
      el.classList.remove('swipe-stamp--visible');
    });
  }

  function getAction() {
    const absX = Math.abs(dx), absY = Math.abs(dy);
    if (Math.max(absX, absY) < 40) return null;
    if (absY > absX) return dy < 0 ? 'unsure' : 'superdislike';
    return dx > 0 ? 'like' : 'dislike';
  }

  function applyTransform() {
    if (!card) return;
    const absX = Math.abs(dx), absY = Math.abs(dy);
    const translateX = Math.max(-420, Math.min(420, dx));
    const translateY = Math.max(-420, Math.min(420, dy));
    const rotate = dx * 0.05;
    card.style.transition = 'none';
    card.style.transform = `translateX(${translateX}px) translateY(${translateY}px) rotate(${rotate}deg)`;
    const opacity = 1 - Math.min(0.4, Math.max(absX, absY) / 900);
    card.style.opacity = opacity;
    const action = getAction();
    if (action) {
      showStamp(action);
    } else {
      clearStamp();
    }
  }

  function resetTransform() {
    if (!card) return;
    card.style.transition = 'transform 0.3s ease, opacity 0.3s ease';
    card.style.transform = '';
    card.style.opacity = '';
    card.style.removeProperty('--swipe-tint');
    clearStamp();
    setTimeout(() => { if (card) { card.style.transition = ''; card.style.cursor = ''; } }, 300);
  }

  function flyOff(action) {
    if (!card) return;
    const flyX = action === 'like' ? 520 : action === 'dislike' ? -520 : 0;
    const flyY = action === 'unsure' ? -520 : action === 'superdislike' ? 520 : 0;
    const flyRot = action === 'like' ? 20 : action === 'dislike' ? -20 : 0;
    card.style.transition = 'transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.35s ease';
    card.style.transform = `translateX(${flyX}px) translateY(${flyY}px) rotate(${flyRot}deg)`;
    card.style.opacity = '0';
    clearStamp();
    setTimeout(() => {
      handleAction(action);
      card = null;
    }, 350);
  }

  // Use the card itself as the drag target — pointer events will retarget
  // to the element that has pointer capture, so we must attach move/up/cancel
  // listeners to the same element that receives the pointerdown.
  container.addEventListener('pointerdown', (e) => {
    if (state.busy || !state.current) return;
    // Ignore clicks on interactive elements inside the card
    if (e.target.closest('button, select, input, details, summary, a')) return;
    card = e.target.closest('.job-card') || container.querySelector('.job-card');
    if (!card) return;
    // Kill the enter animation before dragging: its `forwards` fill pins the
    // final keyframe transform on the element, which would override the
    // inline transform we set below — the card would never move.
    card.classList.remove('enter');
    card.style.animation = 'none';
    active = true;
    startX = e.clientX;
    startY = e.clientY;
    dx = 0; dy = 0;
    lastX = e.clientX; lastY = e.clientY; lastT = Date.now();
    velX = 0; velY = 0;
    card.style.transition = 'none';
    card.style.cursor = 'grabbing';
    card.setPointerCapture(e.pointerId);

    // Attach move/up/cancel to the captured element (the card)
    // IMPORTANT: define listeners on the card so pointer events forward correctly
    function onMove(ev) {
      if (!active || !card) return;
      const now = Date.now();
      const dt = Math.max(1, now - lastT);
      velX = (ev.clientX - lastX) / dt * 1000;
      velY = (ev.clientY - lastY) / dt * 1000;
      lastX = ev.clientX; lastY = ev.clientY; lastT = now;
      dx = ev.clientX - startX;
      dy = ev.clientY - startY;
      applyTransform();
    }

    function onUp(ev) {
      if (!active || !card) return;
      active = false;
      card.style.cursor = '';
      card.releasePointerCapture(ev.pointerId);
      card.removeEventListener('pointermove', onMove);
      card.removeEventListener('pointerup', onUp);
      card.removeEventListener('pointercancel', onCancel);
      const action = getAction();
      if (!action) {
        resetTransform();
        return;
      }
      const fast = Math.hypot(velX, velY) > 500;
      if (fast || Math.hypot(dx, dy) > 120) {
        flyOff(action);
      } else {
        resetTransform();
      }
    }

    function onCancel() {
      active = false;
      if (card) {
        card.style.cursor = '';
        card.removeEventListener('pointermove', onMove);
        card.removeEventListener('pointerup', onUp);
        card.removeEventListener('pointercancel', onCancel);
      }
      resetTransform();
    }

    // Bind listeners to the card so pointer events forward correctly under capture
    card.addEventListener('pointermove', onMove);
    card.addEventListener('pointerup', onUp);
    card.addEventListener('pointercancel', onCancel);
  });
}

function bindEnergyWarning() {
  // Energy warning removed in clean swipe template; no-op for compatibility.
}

// ── Daily goal progress + energy guard ───────────────────────────────────────
// Populate + show the superdislike confirmation dialog for the current card.
function confirmSuperdislike() {
  if (state.busy || !state.current) return;
  handleAction('superdislike');
}

function checkEnergyWarning() {
  // Energy warning removed in clean swipe template; no-op for compatibility.
}

async function loadProgressStats() {
  try {
    const data = await getProfileStats();
    if (data.streak) state.streak = data.streak.current || 0;
    if (data.total && data.total.badges_earned != null) state.badgeCount = data.total.badges_earned;
    if (data.total && data.total.total_points != null) state.totalPoints = data.total.total_points;
  } catch (e) {
    // ignore
  }
  updateProgress();
}

async function refreshGoalProgress() {
  try {
    const data = await getProfileStats();
    const today = data.today || {};
    state.dailyTotal = today.total || 0;
    state.dailyGoal = (data.daily_goal && data.daily_goal > 0) ? data.daily_goal : 10;
    if (data.streak) state.streak = data.streak.current || 0;
    if (data.total && data.total.badges_earned != null) state.badgeCount = data.total.badges_earned;
    if (data.total && data.total.total_points != null) state.totalPoints = data.total.total_points;
    // New day (total below cap) re-arms the soft block.
    if (state.dailyTotal < state.energyMax) state.energyAcknowledged = false;
    checkEnergyWarning();
  } catch (e) {
    // Stats unavailable — keep the default daily goal.
  }
  updateProgress();
}

async function getProfileStats() {
  const data = await getStats();
  // getStats returns /api/auth/profile/stats which has {user, today, total, streak, daily_goal}
  return data;
}

async function loadPreferencesMeta() {
  try {
    const prefs = await getPreferences();
    state.energyMax = parseInt(prefs.energy_max_reviews || 0, 10) || 0;
  } catch (e) {
    state.energyMax = 0;
  }
  refreshGoalProgress();
}

function bindSwipeEvents() {
  const bind = (id, action) => {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener('click', () => {
      if (action === 'help') {
        showToast('Shortcuts: ←/D dislike, →/L like, ↓/U unsure, S no fit, Ctrl+Z undo', 'info');
        return;
      }
      if (action === 'undo') {
        undoLast();
        return;
      }
      handleAction(action);
    });
  };

  // Order: superdislike, dislike, unsure, like (left-to-right: most negative to most positive)
  bind('superdislike-btn', 'superdislike');
  bind('dislike-btn', 'dislike');
  bind('unsure-btn', 'unsure');
  bind('like-btn', 'like');
  bind('undo-btn', 'undo');
  bind('interested-btn', 'interested');
  bind('not-interested-btn', 'not-interested');

  // Tracks edit — open the card's extras panel instead of navigating
  const tracksBtn = document.getElementById('tracks-edit-btn');
  if (tracksBtn) {
    tracksBtn.addEventListener('click', () => {
      const details = document.querySelector('.card-extras-panel');
      if (details) {
        details.open = true;
        const trackSelect = details.querySelector('#track-reclassify');
        if (trackSelect) trackSelect.focus();
      }
    });
  }
}

function pushHistory(job, action) {
  if (!job) return;
  state.history.push({ job, action, t: Date.now() });
  if (state.history.length > state.historyLimit) state.history.shift();
}

async function undoLast() {
  if (state.busy || !state.history.length) return;
  const entry = state.history.pop();
  try {
    state.busy = true;
    const res = await fetch(`/api/jobs/${entry.job.id}/revert`, { method: 'POST' });
    if (!res.ok) throw new Error('Revert failed');
    state.queue.unshift(entry.job);
    renderCard();
    showToast(`Undid ${entry.action} — ${entry.job.title}`, 'success');
  } catch (err) {
    state.history.push(entry); // re-push on failure
    showToast(err.message, 'error');
  } finally {
    state.busy = false;
    updateSwipeActionState();
    updateUndoButtonState();
  }
}

// Keep the Undo button's disabled state in sync with the history stack.
function updateUndoButtonState() {
  const undoBtn = document.getElementById('undo-btn');
  if (!undoBtn) return;
  const canUndo = state.history.length > 0;
  undoBtn.disabled = !canUndo;
  undoBtn.setAttribute('aria-disabled', String(!canUndo));
  undoBtn.title = canUndo
    ? `Undo last swipe (Ctrl+Z / Cmd+Z) — ${state.history.length} remaining`
    : 'No swipes to undo yet';
}

// Update both swipe-progress strip (legacy) and topbar stats
function updateProgress() {
  // Legacy bottom strip (may be absent on new layout)
  const streakEl = document.getElementById('progress-streak');
  const badgesEl = document.getElementById('progress-badges');
  const pointsEl = document.getElementById('progress-points');
  if (streakEl) streakEl.textContent = String(state.streak);
  if (badgesEl) badgesEl.textContent = String(state.badgeCount);
  if (pointsEl) pointsEl.textContent = String(state.totalPoints);

  // Topbar stats (always present)
  const topStreak = document.getElementById('topbar-streak');
  const topBadges = document.getElementById('topbar-badges');
  const topPoints = document.getElementById('topbar-points');
  if (topStreak) topStreak.textContent = `🔥 ${state.streak}`;
  if (topBadges) topBadges.textContent = `🏅 ${state.badgeCount}`;
  if (topPoints) topPoints.textContent = `⭐ ${state.totalPoints}`;
}

function bindKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Skip if focus is in an input/textarea/select
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    // Ctrl+Z / Cmd+Z — undo last swipe
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault();
      undoLast();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    switch (e.key) {
      case 'ArrowUp':
      case 'u':
        e.preventDefault();
        handleAction('unsure');
        break;
      case 'ArrowDown':
      case 's':
        e.preventDefault();
        handleAction('superdislike');
        break;
      case 'ArrowRight':
      case 'l':
        e.preventDefault();
        handleAction('like');
        break;
      case 'ArrowLeft':
      case 'd':
        e.preventDefault();
        handleAction('dislike');
        break;
    }
  });
}

function bindAddJob() {
  const buttons = ['add-job-btn', 'mobile-add-job-btn']
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  if (!buttons.length) return;
  buttons.forEach((btn) => btn.addEventListener('click', () => {
    const modal = document.getElementById('add-job-modal');
    if (modal) modal.classList.remove('hidden');
    document.getElementById('add-job-title')?.focus();
  }));
  const closeModal = () => {
    const modal = document.getElementById('add-job-modal');
    if (modal) modal.classList.add('hidden');
  };
  document.getElementById('add-job-cancel')?.addEventListener('click', closeModal);
  document.getElementById('add-job-modal')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });
  document.getElementById('add-job-submit')?.addEventListener('click', async () => {
    const title = document.getElementById('add-job-title')?.value.trim();
    const company = document.getElementById('add-job-company')?.value.trim();
    if (!title || !company) { showToast('Title and company are required', 'error'); return; }
    const link = document.getElementById('add-job-link')?.value.trim();
    const location = document.getElementById('add-job-location')?.value.trim();
    const submitBtn = document.getElementById('add-job-submit');
    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await fetch('/api/jobs/manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, company, link, location }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Could not add job');
      if (data.merged_into) {
        showToast('Merged into existing job #' + data.merged_into, 'success');
      } else {
        showToast('Job added: ' + title, 'success');
      }
      closeModal();
      ['add-job-title', 'add-job-company', 'add-job-link', 'add-job-location'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
      });
      loadQueue();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

async function initSwipePage() {
  bindSwipeEvents();
  bindCardButtons();
  bindCardDrag();
  bindFilterChanges();
  bindMobileFilterPopover();
  bindKeyboardShortcuts();
  bindAddJob();
  updateSwipeActionState();
  await loadFilterOptions();
  loadQueue();
  loadPreferencesMeta();
  loadProgressStats();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSwipePage);
} else {
  initSwipePage();
}
