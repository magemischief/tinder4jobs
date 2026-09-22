let _editingSkill = null;
let _skills = [];

// Gap = what you know vs. what the market wants. Positive = surplus,
// negative = shortfall worth studying. Needs a daemon-computed demand value;
// before the first daemon run demand_auto is NULL and the gap stays blank.
function gapFor(s) {
  if (s.demand_auto === null || s.demand_auto === undefined) return null;
  return Number(s.self_rating || 0) - Number(s.demand_auto);
}

function gapBadge(gap) {
  if (gap === null) return '<span class="score-badge score-unscored">—</span>';
  const cls = gap > 0 ? 'score-high' : gap < 0 ? 'score-low' : 'score-unscored';
  const sign = gap > 0 ? '+' : '';
  return `<span class="score-badge ${cls}">${sign}${gap}</span>`;
}

function renderSkills(rows) {
  const tbody = document.getElementById('skills-tbody');
  const empty = document.getElementById('skills-empty');
  if (!tbody || !empty) return;

  if (!rows.length) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  tbody.innerHTML = rows.map((s) => {
    const demand = s.demand_auto === null || s.demand_auto === undefined
      ? '—'
      : `${escapeHTML(String(s.demand_auto))}/5`;
    const jobs = s.demand_job_count === null || s.demand_job_count === undefined
      ? '—'
      : escapeHTML(String(s.demand_job_count));
    return `
      <tr>
        <td>${escapeHTML(s.skill || '')}</td>
        <td>${escapeHTML(String(s.self_rating || 3))}/5</td>
        <td>${demand}</td>
        <td>${jobs}</td>
        <td>${gapBadge(gapFor(s))}</td>
        <td>${escapeHTML(s.notes || '')}</td>
        <td>${escapeHTML(s.updated_at || '')}</td>
        <td class="row-actions">
          <button class="btn btn--sm btn--ghost js-edit-skill" data-skill="${escapeHTML(s.skill || '')}" type="button">Edit</button>
          <button class="btn btn--sm btn--danger-ghost js-delete-skill" data-skill="${escapeHTML(s.skill || '')}" type="button">Delete</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function loadSkills() {
  try {
    const res = await fetch('/api/skills');
    if (!res.ok) throw new Error('Failed to load skills');
    const data = await res.json();
    _skills = data.skills || [];
    renderSkills(_skills);
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function resetEditState(form) {
  _editingSkill = null;
  form.reset();
  form.querySelector('button[type="submit"]').textContent = 'Add / Update';
  const cancel = document.getElementById('skill-cancel-edit');
  if (cancel) cancel.style.display = 'none';
}

async function deleteSkill(skill) {
  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(skill)}`, { method: 'DELETE' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Failed to delete (${res.status})`);
    }
    showToast('Skill deleted', 'success');
    await loadSkills();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function initSkillsPage() {
  const tbody = document.getElementById('skills-tbody');
  const form = document.getElementById('new-skill-form');
  if (!tbody || !form) return;

  tbody.addEventListener('click', async (e) => {
    const editBtn = e.target.closest('.js-edit-skill');
    const delBtn = e.target.closest('.js-delete-skill');
    if (editBtn) {
      const skill = editBtn.dataset.skill;
      const row = _skills.find((s) => s.skill === skill);
      if (!row) return;
      form.querySelector('[name="skill"]').value = row.skill || '';
      form.querySelector('[name="self_rating"]').value = String(row.self_rating || 3);
      form.querySelector('[name="notes"]').value = row.notes || '';
      _editingSkill = skill;
      form.querySelector('button[type="submit"]').textContent = 'Update';
      const cancel = document.getElementById('skill-cancel-edit');
      if (cancel) cancel.style.display = '';
      form.scrollIntoView({ behavior: 'smooth' });
    } else if (delBtn) {
      await deleteSkill(delBtn.dataset.skill);
    }
  });

  document.getElementById('skill-cancel-edit')?.addEventListener('click', (e) => {
    e.preventDefault();
    resetEditState(form);
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = Object.fromEntries(fd.entries());
    payload.self_rating = Number(payload.self_rating);
    const oldName = _editingSkill;
    try {
      const res = await fetch('/api/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to save skill');
      }
      // Rename flow: POST upserts under the new name, so the row stored under
      // the old name must be removed or it lingers as a duplicate.
      if (oldName && oldName !== payload.skill) {
        await fetch(`/api/skills/${encodeURIComponent(oldName)}`, { method: 'DELETE' });
      }
      resetEditState(form);
      showToast('Skill saved', 'success');
      await loadSkills();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  loadSkills();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSkillsPage);
} else {
  initSkillsPage();
}
