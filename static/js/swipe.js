const state = {
  queue: [],
  current: null,
  busy: false,
};

function updateCount() {
  const el = document.getElementById('queue-count');
  if (el) el.textContent = String(state.queue.length);
}

function renderCard() {
  const container = document.getElementById('card-container');
  const emptyState = document.getElementById('empty-state');
  const actions = document.getElementById('actions');

  if (!state.queue.length) {
    container.innerHTML = '';
    emptyState.classList.remove('hidden');
    actions.hidden = true;
    updateCount();
    return;
  }

  const job = state.queue[0];
  state.current = job;
  emptyState.classList.add('hidden');
  actions.hidden = false;

  const locations = (job.locations || []).map(escapeHTML).join(' · ') || 'Remote / Not listed';
  const description = escapeHTML(job.description || 'No description provided.');
  const status = escapeHTML(job.status || 'Review to Apply');
  const sourceTab = escapeHTML(job.source_tab || '');
  const track = escapeHTML(job.track || '');
  const rawLink = safeUrl(job.link);
  const linkHtml = rawLink
    ? `<a class="card-link" href="${escapeHTML(rawLink)}" target="_blank" rel="noopener noreferrer">View original posting →</a>`
    : '';

  container.innerHTML = `
    <article class="job-card enter" data-job-id="${job.id}">
      <div class="card-top">
        <span class="badge">${status}</span>
        <span class="text-muted">${escapeHTML(job.date_found || '')}</span>
      </div>
      <div class="card-body">
        <h2>${escapeHTML(job.title)}</h2>
        <h3>${escapeHTML(job.company)}</h3>
        <p class="card-location">${locations}</p>
        ${job.salary ? `<p class="card-salary">${escapeHTML(job.salary)}</p>` : ''}
        ${linkHtml}
        <div class="card-description">${description}</div>
      </div>
      <div class="card-footer">
        <span>${sourceTab || 'Imported'}</span>
        <span>Row ${job.source_row ?? '—'}</span>
        <span>${track || ''}</span>
      </div>
    </article>
  `;

  updateCount();
}

function animateCardExit(direction) {
  const card = document.querySelector('.job-card');
  if (!card) return Promise.resolve();

  return new Promise((resolve) => {
    card.classList.add(`exit-${direction}`);
    card.addEventListener('transitionend', () => resolve(), { once: true });
    setTimeout(resolve, 400);
  });
}

async function handleAction(action) {
  if (state.busy || !state.current) return;
  state.busy = true;

  const job = state.current;

  if (action === 'unsure') {
    const wasLast = state.queue.length <= 1;
    // No DB write. The card goes to the back of the runtime queue array.
    state.queue.shift();
    state.queue.push(job);
    await animateCardExit('unsure');
    renderCard();
    state.busy = false;

    if (wasLast) {
      showToast('Only one card remains. Use Like or Dislike to resolve it.', 'warning');
    }
    return;
  }

  let response;
  try {
    response = await fetch(`/api/jobs/${job.id}/swipe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
  } catch (error) {
    showToast('Network error – could not update job', 'error');
    state.busy = false;
    return;
  }

  if (!response.ok) {
    let data = {};
    try {
      data = await response.json();
    } catch (_) {
      // ignore
    }
    showToast(data.error || 'Could not update job', 'error');
    state.busy = false;
    return;
  }

  state.queue.shift();
  const direction = action === 'like' ? 'right' : 'left';
  await animateCardExit(direction);
  renderCard();
  state.busy = false;
}

async function loadQueue() {
  state.busy = true;
  try {
    const response = await fetch('/api/review/queue?limit=200');
    if (!response.ok) throw new Error('Failed to load queue');
    const data = await response.json();
    state.queue = data.jobs || [];
    state.current = null;
    renderCard();
  } catch (error) {
    document.getElementById('card-container').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <h2>Could not load the queue</h2>
        <p>${escapeHTML(error.message)}</p>
      </div>
    `;
    document.getElementById('actions').hidden = true;
  } finally {
    state.busy = false;
  }
}

document.getElementById('like-btn').addEventListener('click', () => handleAction('like'));
document.getElementById('dislike-btn').addEventListener('click', () => handleAction('dislike'));
document.getElementById('unsure-btn').addEventListener('click', () => handleAction('unsure'));
document.getElementById('refresh-queue').addEventListener('click', loadQueue);

loadQueue();