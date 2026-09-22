/**
 * ui.js — shared rendering helpers (deduplicated from swipe.js + application.js).
 * Why: scoreBucket/atsBadge/salary/location cleanup were copy-pasted across
 * pages and drifted. Import from here instead of duplicating.
 */

function scoreBucket(score) {
  if (score == null || score === 0) return 'unscored';
  if (score >= 7) return 'high';
  if (score >= 4) return 'medium';
  return 'low';
}

function scoreBadgeHTML(score) {
  const raw = score;
  if (raw == null || raw <= 0) {
    return `<span class="score-badge score-unscored" title="Not yet scored">—</span>`;
  }
  return `<span class="score-badge score-${scoreBucket(raw)}">${escapeHTML(String(raw))}<span class="score-suffix">/10</span></span>`;
}

/** AI-in-hiring badge: rendered only when the posting signals AI in the hiring funnel. */
function aiBadgeHTML(job) {
  if (!job || job.uses_ai !== true) return '';
  const sig = job.ai_signal ? String(job.ai_signal).trim() : '';
  return `<span class="ats-badge ats-ai" title="Employer's hiring process uses AI${sig ? ` (${escapeHTML(sig)})` : ''}">🧠 AI hiring</span>`;
}

function atsBadgeHTML(job) {
  const usesAts = job ? job.uses_ats : null;
  const atsName = job && job.ats_name ? String(job.ats_name).trim() : '';
  const applyType = job && job.apply_type ? String(job.apply_type).trim() : '';
  let ats;
  if (usesAts === true) {
    const label = atsName ? `ATS · ${atsName}` : 'Uses ATS';
    ats = `<span class="ats-badge ats-yes" title="This posting routes through an applicant tracking system${atsName ? ` (${atsName})` : ''}">🤖 ${escapeHTML(label)}</span>`;
  } else if (usesAts === false) {
    const label = applyType || 'Easy Apply';
    ats = `<span class="ats-badge ats-no" title="No external ATS redirect — apply inline on the job board">⚡ ${escapeHTML(label)}</span>`;
  } else {
    ats = `<span class="ats-badge ats-unknown" title="Could not tell from the posting link/description whether an ATS is used">❔ ATS unknown</span>`;
  }
  // The AI-hiring marker rides along with the ATS badge so every surface that
  // shows one shows the other (swipe card header, applications table, Top-3).
  return ats + aiBadgeHTML(job);
}

/** Hide junk pay strings ("None-None None", "nan", punctuation-only). */
function cleanSalaryText(raw) {
  const s = raw == null ? '' : String(raw).trim();
  if (!s || /none|nan/i.test(s) || /^\W*$/.test(s)) return '';
  return s;
}

function structuredSalaryText(min, max, currency) {
  const cur = currency || '$';
  const fmt = (n) => cur + Number(n).toLocaleString();
  if (min && max) return `${fmt(min)} – ${fmt(max)}`;
  if (min) return `From ${fmt(min)}`;
  if (max) return `Up to ${fmt(max)}`;
  return '';
}

/** Dedupe + drop placeholder location strings. */
function cleanLocations(list) {
  const seen = new Set();
  const out = [];
  (list || []).forEach((loc) => {
    const v = loc == null ? '' : String(loc).trim();
    if (!v || /^(none|n\/a|na)$/i.test(v)) return;
    const key = v.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push(v);
  });
  return out;
}

/** Days from today until an YYYY-MM-DD (or datetime) deadline; null if unparseable. */
function daysUntilDeadline(deadline) {
  if (!deadline) return null;
  const d = new Date(String(deadline).slice(0, 10) + 'T23:59:59');
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((d - today) / 86400000);
}

/** Urgency pill for a deadline: overdue / due-soon (<=3d) / normal / ''. */
function deadlinePillHTML(deadline) {
  if (!deadline) return '';
  const days = daysUntilDeadline(deadline);
  if (days === null) return `<p class="card-deadline">Apply by ${escapeHTML(deadline)}</p>`;
  if (days < 0) return `<p class="card-deadline deadline-overdue">Overdue since ${escapeHTML(deadline)}</p>`;
  if (days <= 3) return `<p class="card-deadline deadline-soon">Apply by ${escapeHTML(deadline)} · ${days === 0 ? 'due today' : `due in ${days}d`}</p>`;
  return `<p class="card-deadline">Apply by ${escapeHTML(deadline)}</p>`;
}
