async function loadLetters() {
  try {
    const res = await fetch('/api/cover-letters');
    if (!res.ok) throw new Error('Failed to load cover letters');
    const data = await res.json();
    renderLetters(data.cover_letters || []);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function renderLetters(letters) {
  const list = document.getElementById('letters-list');
  const empty = document.getElementById('letters-empty');
  if (!list || !empty) return;

  if (!letters.length) {
    list.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  list.innerHTML = letters.map((l) => {
    const bodyPreview = (l.body || '').slice(0, 160);
    const bodyEscaped = escapeHTML(l.body || '');
    return `
      <article class="letter-card">
        <div class="letter-header">
          <h3>${escapeHTML(l.title || 'Untitled')}</h3>
          <button class="btn btn--sm btn--danger-ghost js-delete" data-id="${l.id}" type="button">Delete</button>
        </div>
        <pre class="letter-body">${escapeHTML(bodyPreview)}${(l.body || '').length > 160 ? '…' : ''}</pre>
        <button class="btn btn--sm btn--ghost js-copy" data-body="${bodyEscaped}" type="button">Copy to clipboard</button>
      </article>
    `;
  }).join('');
}

function bindLetterActions() {
  const list = document.getElementById('letters-list');
  if (!list) return;

  list.addEventListener('click', async (e) => {
    const delBtn = e.target.closest('.js-delete');
    if (delBtn) {
      e.preventDefault();
      const id = delBtn.dataset.id;
      if (delBtn.dataset.confirm === '1') {
        try {
          const res = await fetch(`/api/cover-letters/${id}`, { method: 'DELETE' });
          if (!res.ok) throw new Error('Delete failed');
          showToast('Template deleted', 'success');
          await loadLetters();
        } catch (err) {
          showToast(err.message, 'error');
        }
        return;
      }
      delBtn.dataset.confirm = '1';
      delBtn.textContent = 'Confirm?';
      delBtn.classList.add('btn--danger');
      delBtn.classList.remove('btn--danger-ghost');
      setTimeout(() => {
        delete delBtn.dataset.confirm;
        delBtn.textContent = 'Delete';
        delBtn.classList.remove('btn--danger');
        delBtn.classList.add('btn--danger-ghost');
      }, 2500);
      return;
    }

    const copyBtn = e.target.closest('.js-copy');
    if (copyBtn) {
      e.preventDefault();
      const body = copyBtn.dataset.body || '';
      const textarea = document.createElement('textarea');
      textarea.value = body;
      document.body.appendChild(textarea);
      textarea.select();
      try { document.execCommand('copy'); showToast('Copied to clipboard', 'success'); }
      catch (_) { showToast('Copy failed — select manually', 'error'); }
      document.body.removeChild(textarea);
    }
  });
}

document.getElementById('new-letter-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    title: (fd.get('title') || '').trim(),
    body: (fd.get('body') || '').trim(),
  };
  if (!payload.title || !payload.body) {
    showToast('Title and body are required', 'error');
    return;
  }
  try {
    const res = await fetch('/api/cover-letters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Failed to save template');
    }
    e.target.reset();
    showToast('Template saved', 'success');
    await loadLetters();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

bindLetterActions();
loadLetters();