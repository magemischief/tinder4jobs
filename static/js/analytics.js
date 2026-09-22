async function loadAnalytics() {
  try {
    const res = await fetch('/api/analytics');
    if (!res.ok) throw new Error('Failed to load analytics');
    const data = await res.json();
    renderAnalytics(data);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderAnalytics(data) {
  const pipeline = data.pipeline || {};
  const totalReviews = Number(pipeline.reviewed || (data.daily_reviews || []).reduce((s, d) => s + Number(d.total || 0), 0));
  const liked = Number(pipeline.liked || 0);
  const applied = Number(pipeline.applied || 0);
  const readyToApply = Number(pipeline.ready_to_apply || 0);
  const queueCount = Number(pipeline.queue_count || 0);
  const daysWithReviews = (data.daily_reviews || []).filter(d => Number(d.total || 0) > 0).length;
  const avgPerDay = daysWithReviews ? (totalReviews / daysWithReviews).toFixed(1) : '0';
  const likeRate = totalReviews ? Math.round((liked / totalReviews) * 100) : 0;
  const applyRate = liked ? Math.round((applied / liked) * 100) : 0;

  setText('total-reviews', totalReviews);
  setText('avg-score', data.avg_relevance_score != null ? data.avg_relevance_score + '/10' : '—');
  setText('avg-per-day', avgPerDay);
  setText('active-days', `${daysWithReviews} active day${daysWithReviews === 1 ? '' : 's'}`);
  setText('like-rate', `${likeRate}%`);
  setText('liked-count', `${liked} kept`);
  setText('applied-count', applied);
  setText('apply-rate', liked ? `${applyRate}% of liked jobs` : 'Keep jobs to measure this');
  setText('pipeline-reviewed', totalReviews);
  setText('pipeline-liked', liked);
  setText('pipeline-applied', applied);
  setText('queue-count-insight', `${queueCount} in queue`);

  renderTrackBreakdown(data.by_track || []);
  renderCompanyBreakdown(data.top_liked_companies || []);
  renderNextAction({ totalReviews, liked, applied, readyToApply, queueCount });

  renderDaily(data.daily_reviews || []);
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(value);
}

function renderCompanyBreakdown(rows) {
  const ul = document.getElementById('top-liked');
  if (!ul) return;
  if (!rows.length) {
    ul.innerHTML = '<li class="analytics-empty">Keep a job to build your company shortlist.</li>';
    return;
  }
  ul.innerHTML = rows.slice(0, 5).map((row) => `
    <li class="analytics-row"><span>${escapeHTML(row.company || 'Unknown company')}</span><strong>${Number(row.total || 0)} saved</strong></li>
  `).join('');
}

function renderTrackBreakdown(rows) {
  const ul = document.getElementById('by-track');
  if (!ul) return;
  if (!rows.length) {
    ul.innerHTML = '<li class="analytics-empty">Review a few jobs to see which tracks are earning your attention.</li>';
    return;
  }
  const max = Math.max(...rows.map((row) => Number(row.total || 0)), 1);
  ul.innerHTML = rows.slice(0, 5).map((row) => {
    const total = Number(row.total || 0);
    const liked = Number(row.liked || 0);
    const applied = Number(row.applied || 0);
    const percent = Math.max(6, Math.round((total / max) * 100));
    const score = row.avg_score ? `${(Number(row.avg_score) / 10).toFixed(1)}/10 avg` : 'No score yet';
    return `<li class="analytics-track-row">
      <div class="analytics-row"><span>${escapeHTML(row.track || 'Untracked')}</span><strong>${total} reviewed</strong></div>
      <div class="analytics-track-meter"><span style="width:${percent}%"></span></div>
      <small>${liked} kept · ${applied} applied · ${score}</small>
    </li>`;
  }).join('');
}

function renderNextAction({ totalReviews, liked, applied, readyToApply, queueCount }) {
  let title = 'Start with one thoughtful review';
  let copy = 'A small review session is enough to begin learning what you want to pursue.';
  let href = '/review';
  let label = 'Review jobs';
  let icon = '→';

  if (readyToApply > 0) {
    title = `${readyToApply} saved job${readyToApply === 1 ? ' is' : 's are'} ready to apply`;
    copy = 'Convert your strongest matches while they are still fresh.';
    href = '/applications';
    label = 'Open applications';
    icon = '↗';
  } else if (liked > 0 && applied === 0) {
    title = 'Turn a saved job into an application';
    copy = 'You have promising jobs on hand. Pick the strongest fit and take the next concrete step.';
    href = '/applications';
    label = 'Open applications';
    icon = '↗';
  } else if (queueCount > 0) {
    title = `Clear a focused batch of ${Math.min(queueCount, 5)}`;
    copy = 'A short session keeps your pipeline moving without turning the search into a grind.';
  } else if (totalReviews > 0) {
    title = 'Your review queue is clear';
    copy = 'Add a job manually or return when new opportunities arrive.';
    label = 'Add a job';
  }

  setText('next-action-title', title);
  setText('next-action-copy', copy);
  setText('next-action-icon', icon);
  const link = document.getElementById('next-action-link');
  if (link) { link.href = href; link.innerHTML = `${escapeHTML(label)} <span aria-hidden="true">→</span>`; }
}

function renderDaily(rows) {
  const el = document.getElementById('daily-chart');
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = '<div class="text-muted">No reviews in the last 30 days</div>';
    return;
  }
  const max = Math.max(...rows.map((r) => Number(r.total || 0)), 1);
  const labels = rows.map((r) => escapeHTML(r.d));
  const values = rows.map((r) => Number(r.total || 0));
  // Build a simple horizontal bar chart
  el.innerHTML = rows.map((r, i) => {
    const h = (Number(r.total || 0) / max) * 100;
    return `<div class="bar" title="${labels[i]}: ${values[i]}" style="height:${h}%"><span>${values[i]}</span></div>`;
  }).join('');
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadAnalytics);
} else {
  loadAnalytics();
}
