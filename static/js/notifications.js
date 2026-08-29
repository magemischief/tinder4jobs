async function loadNotifications() {
  try {
    const res = await fetch('/api/notifications');
    if (!res.ok) throw new Error('Failed to load notifications');
    const data = await res.json();
    renderNotifications(data.jobs || []);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function renderNotifications(jobs) {
  const banner = document.getElementById('notification-banner');
  const list = document.getElementById('notifications-list');
  const empty = document.getElementById('notifications-empty');

  if (!jobs.length) {
    banner.classList.add('hidden');
    list.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }

  banner.classList.remove('hidden');
  banner.innerHTML = `
    <span class="banner-icon">⚠️</span>
    <div>
      <strong>${jobs.length} active job${jobs.length === 1 ? '' : 's'} awaiting response.</strong>
      <div class="text-muted">Review follow-up dates and targeted email statuses from the refactored jobcheck.py run.</div>
    </div>
  `;

  list.innerHTML = jobs
    .map((job) => {
      const rawLink = safeUrl(job.link);
      const linkHtml = rawLink
        ? `<a class="link-button" href="${escapeHTML(rawLink)}" target="_blank" rel="noopener noreferrer">Open posting →</a>`
        : '';

      return `
        <article class="notification-card">
          <div class="notification-header">
            <span class="badge warning">${escapeHTML(job.status || 'Awaiting Response')}</span>
            <span class="text-muted">${escapeHTML(job.updated_at || '')}</span>
          </div>
          <h3>${escapeHTML(job.title)}</h3>
          <p>${escapeHTML(job.company)}</p>
          ${job.follow_up_sent ? `<p><strong>Follow-up sent:</strong> ${escapeHTML(job.follow_up_sent)}</p>` : ''}
          ${job.interview_date ? `<p><strong>Interview date:</strong> ${escapeHTML(job.interview_date)}</p>` : ''}
          ${linkHtml}
        </article>
      `;
    })
    .join('');

  empty.classList.add('hidden');
}

loadNotifications();