let _editingId = null;

async function loadInterviews() {
  try {
    const res = await fetch('/api/interviews');
    if (!res.ok) throw new Error('Failed to load interviews');
    const data = await res.json();
    renderInterviews(data.interviews || []);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function relativeDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const days = Math.round((d - Date.now()) / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days === -1) return 'yesterday';
  if (days > 0 && days < 7) return `in ${days}d`;
  if (days < 0 && days > -7) return `${-days}d ago`;
  return iso;
}

function renderInterviews(rows) {
  const tbody = document.getElementById('interviews-tbody');
  const empty = document.getElementById('interviews-empty');
  if (!tbody || !empty) return;

  if (!rows.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = rows.map((i) => `
    <tr data-id="${i.id}">
      <td>${escapeHTML(i.company || '')}</td>
      <td>${escapeHTML(i.role || '')}</td>
      <td>${escapeHTML(relativeDate(i.interview_date))}</td>
      <td>${escapeHTML(relativeDate(i.follow_up_at))}</td>
      <td>${escapeHTML(i.prep_notes || '')}</td>
      <td>${escapeHTML(i.questions_to_ask || '')}</td>
      <td class="row-actions">
        <button class="btn btn--sm btn--ghost js-edit" data-id="${i.id}" type="button">Edit</button>
        <button class="btn btn--sm btn--danger-ghost js-delete" data-id="${i.id}" type="button">Delete</button>
      </td>
    </tr>
  `).join('');
}

// Edit: populate form from row
document.getElementById('interviews-tbody').addEventListener('click', async (e) => {
  const editBtn = e.target.closest('.js-edit');
  const delBtn = e.target.closest('.js-delete');
  if (editBtn) {
    const id = Number(editBtn.dataset.id);
    const row = document.querySelector(`tr[data-id="${id}"]`);
    if (!row) return;
    const cells = row.querySelectorAll('td');
    const form = document.getElementById('new-interview-form');
    form.querySelector('[name="company"]').value = cells[0].textContent;
    form.querySelector('[name="role"]').value = cells[1].textContent;
    _editingId = id;
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.textContent = 'Update';
    showToast('Editing — update fields and save', 'info');
    form.scrollIntoView({ behavior: 'smooth' });
  } else if (delBtn) {
    const id = Number(delBtn.dataset.id);
    await deleteInterview(id);
  }
});

async function deleteInterview(id) {
  try {
    const res = await fetch(`/api/interviews/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete');
    showToast('Interview deleted', 'success');
    await loadInterviews();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

document.getElementById('new-interview-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  for (const k of ['interview_date', 'follow_up_at', 'prep_notes', 'questions_to_ask']) {
    if (payload[k] === '') payload[k] = null;
  }
  if (_editingId) payload.interview_id = _editingId;
  try {
    const res = await fetch('/api/interviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to save interview');
    }
    e.target.reset();
    _editingId = null;
    e.target.querySelector('button[type="submit"]').textContent = 'Add / Update';
    showToast('Interview saved', 'success');
    await loadInterviews();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// Prefill form from URL query params (notifications "Schedule interview" link).
function prefillFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const companyInput = document.querySelector('#new-interview-form [name="company"]');
  const roleInput = document.querySelector('#new-interview-form [name="role"]');
  if (params.get('company') && companyInput) companyInput.value = params.get('company');
  if (params.get('role') && roleInput) roleInput.value = params.get('role');
  if (params.get('company')) {
    const banner = document.getElementById('prefill-banner');
    if (banner) banner.classList.remove('hidden');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { prefillFromQuery(); loadInterviews(); });
} else {
  prefillFromQuery();
  loadInterviews();
}
