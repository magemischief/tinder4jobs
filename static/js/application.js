const state = { jobs: [] };

async function loadApplications() {
  const search = document.getElementById('search-input').value.trim();

  try {
    const res = await fetch(`/api/applications?q=${encodeURIComponent(search)}`);
    if (!res.ok) throw new Error('Failed to load applications');
    const data = await res.json();
    state.jobs = data.jobs || [];
    renderRows();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function renderRows() {
  const tbody = document.getElementById('applications-tbody');
  const empty = document.getElementById('applications-empty');

  if (!state.jobs.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }

  empty.classList.add('hidden');

  tbody.innerHTML = state.jobs
    .map((job) => {
      const locations = (job.locations || []).map(escapeHTML).join(', ') || '—';
      const rawLink = safeUrl(job.link);
      const link = rawLink
        ? `<a class="link-button" href="${escapeHTML(rawLink)}" target="_blank" rel="noopener noreferrer">Open ↗</a>`
        : '—';
      const salary = job.salary ? escapeHTML(job.salary) : '—';
      const dateFound = job.date_found ? escapeHTML(job.date_found) : '—';

      return `
        <tr data-job-id="${job.id}">
          <td>${escapeHTML(job.title)}</td>
          <td>${escapeHTML(job.company)}</td>
          <td>${locations}</td>
          <td>${salary}</td>
          <td>${dateFound}</td>
          <td>${link}</td>
          <td>
            <button class="btn btn-primary mark-applied" data-id="${job.id}">
              Mark as Applied
            </button>
          </td>
        </tr>
      `;
    })
    .join('');
}

async function markApplied(jobId) {
  const button = document.querySelector(`.mark-applied[data-id="${jobId}"]`);
  if (!button) return;

  button.disabled = true;

  try {
    const res = await fetch(`/api/jobs/${jobId}/apply`, { method: 'POST' });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Could not mark as applied');
    }

    state.jobs = state.jobs.filter((job) => job.id !== jobId);
    renderRows();
    showToast('Job marked as Applied', 'success');
  } catch (error) {
    button.disabled = false;
    showToast(error.message, 'error');
  }
}

document.getElementById('applications-tbody').addEventListener('click', (event) => {
  const button = event.target.closest('.mark-applied');
  if (button) markApplied(Number(button.dataset.id));
});

document.getElementById('search-input').addEventListener('input', debounce(loadApplications, 200));

loadApplications();