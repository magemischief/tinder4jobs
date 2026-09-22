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
  const totalReviews = (data.daily_reviews || []).reduce((s, d) => s + Number(d.total || 0), 0);
  const daysWithReviews = (data.daily_reviews || []).filter(d => Number(d.total || 0) > 0).length;
  const avgPerDay = daysWithReviews ? (totalReviews / daysWithReviews).toFixed(1) : '0';

  setText('total-reviews', totalReviews);
  setText('avg-score', data.avg_relevance_score != null ? data.avg_relevance_score + '/10' : '—');
  setText('avg-per-day', avgPerDay);
  setText('active-days', daysWithReviews);

  renderList('by-track', data.by_track || [], (r) => `${r.track || 'unknown'}: ${r.total}`);
  renderList('by-source', data.by_source || [], (r) => `${r.source_tab || 'unknown'}: ${r.total}`);
  renderList('top-liked', data.top_liked_companies || [], (r) => `${r.company}: ${r.total}`);

  renderDaily(data.daily_reviews || []);
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(value);
}

function renderList(id, rows, fmt) {
  const ul = document.getElementById(id);
  if (!ul) return;
  if (!rows.length) {
    ul.innerHTML = '<li class="text-muted">No data yet</li>';
    return;
  }
  ul.innerHTML = rows.map((r) => `<li>${escapeHTML(fmt(r))}</li>`).join('');
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
