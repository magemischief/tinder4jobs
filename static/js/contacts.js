let _editingId = null;
let _allContacts = [];

function warmthBadge(level) {
  const labels = { 1: 'Cold', 2: 'Warm', 3: 'Hot' };
  const cls = level >= 3 ? 'warmth-hot' : level === 2 ? 'warmth-warm' : 'warmth-cold';
  return `<span class="warmth-badge ${cls}">${escapeHTML(labels[level] || 'Cold')}</span>`;
}

async function loadContacts() {
  try {
    const res = await fetch('/api/contacts');
    if (!res.ok) throw new Error('Failed to load contacts');
    const data = await res.json();
    _allContacts = data.contacts || [];
    renderContacts(_allContacts);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderContacts(rows) {
  const tbody = document.getElementById('contacts-tbody');
  const empty = document.getElementById('contacts-empty');
  if (!tbody || !empty) return;

  if (!rows.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = rows.map((c) => {
    const linkedIn = safeUrl(c.linkedin_url);
    return `
    <tr data-id="${c.id}">
      <td>${escapeHTML(c.name || '')}</td>
      <td>${escapeHTML(c.company || '')}</td>
      <td>${escapeHTML(c.role || '')}</td>
      <td>${c.email ? `<a href="mailto:${escapeHTML(c.email)}">${escapeHTML(c.email)}</a>` : '—'}</td>
      <td>${linkedIn ? `<a class="link-button" href="${escapeHTML(linkedIn)}" target="_blank" rel="noopener noreferrer">LinkedIn ↗</a>` : '—'}</td>
      <td>${warmthBadge(Number(c.warmth || 1))}</td>
      <td>${escapeHTML(c.notes || '')}</td>
      <td class="row-actions">
        <button class="btn btn--sm btn--ghost js-edit" data-id="${c.id}" type="button">Edit</button>
        <button class="btn btn--sm btn--danger-ghost js-delete" data-id="${c.id}" type="button">Delete</button>
      </td>
    </tr>
  `;
  }).join('');
}

function filterContacts() {
  const q = (document.getElementById('contacts-search')?.value || '').toLowerCase().trim();
  if (!q) { renderContacts(_allContacts); return; }
  const filtered = _allContacts.filter((c) =>
    (c.name || '').toLowerCase().includes(q) ||
    (c.company || '').toLowerCase().includes(q) ||
    (c.role || '').toLowerCase().includes(q) ||
    (c.email || '').toLowerCase().includes(q)
  );
  renderContacts(filtered);
}

document.getElementById('contacts-tbody').addEventListener('click', async (e) => {
  const editBtn = e.target.closest('.js-edit');
  const delBtn = e.target.closest('.js-delete');
  if (editBtn) {
    const id = Number(editBtn.dataset.id);
    const contact = _allContacts.find((c) => c.id === id);
    if (!contact) return;
    const form = document.getElementById('new-contact-form');
    form.querySelector('[name="name"]').value = contact.name || '';
    form.querySelector('[name="company"]').value = contact.company || '';
    form.querySelector('[name="role"]').value = contact.role || '';
    form.querySelector('[name="email"]').value = contact.email || '';
    form.querySelector('[name="linkedin"]').value = contact.linkedin_url || '';
    form.querySelector('[name="warmth"]').value = String(contact.warmth || 1);
    form.querySelector('[name="notes"]').value = contact.notes || '';
    _editingId = id;
    form.querySelector('button[type="submit"]').textContent = 'Update';
    document.getElementById('contact-cancel-edit').style.display = '';
    form.scrollIntoView({ behavior: 'smooth' });
  } else if (delBtn) {
    const id = Number(delBtn.dataset.id);
    await deleteContact(id);
  }
});

async function deleteContact(id) {
  try {
    const res = await fetch(`/api/contacts/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete');
    showToast('Contact deleted', 'success');
    await loadContacts();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

document.getElementById('new-contact-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  payload.warmth = Number(payload.warmth || 1);
  try {
    let res;
    if (_editingId) {
      res = await fetch(`/api/contacts/${_editingId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } else {
      res = await fetch('/api/contacts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to save contact');
    }
    e.target.reset();
    _editingId = null;
    e.target.querySelector('button[type="submit"]').textContent = 'Add contact';
    document.getElementById('contact-cancel-edit').style.display = 'none';
    showToast('Contact saved', 'success');
    await loadContacts();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

document.getElementById('contact-cancel-edit')?.addEventListener('click', (e) => {
  e.preventDefault();
  const form = document.getElementById('new-contact-form');
  form.reset();
  _editingId = null;
  form.querySelector('button[type="submit"]').textContent = 'Add contact';
  e.target.style.display = 'none';
});

const searchInput = document.getElementById('contacts-search');
if (searchInput) searchInput.addEventListener('input', debounce(filterContacts, 200));

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadContacts);
} else {
  loadContacts();
}
