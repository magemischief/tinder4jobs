/**
 * preferences.js — load, display, and save user preferences.
 */
(async function () {
  const userData = await requireAuth();
  if (!userData) return; // redirected to /login

  const FIELDS = [
    { key: 'default_keywords',     inputId: 'pref-keywords',     chipsId: 'pref-keywords-chips' },
    { key: 'blacklist_terms',      inputId: 'pref-blacklist',    chipsId: 'pref-blacklist-chips' },
  ];

  let currentPrefs = {};

  // ── Chip helpers ───────────────────────────────────────────────────────────

  function makeChip(label, onRemove) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = label;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip-remove';
    btn.textContent = '×';
    btn.onclick = () => {
      chip.remove();
      onRemove(label);
    };
    chip.appendChild(btn);
    return chip;
  }

  function populateChips(field, items) {
    const container = document.getElementById(field.chipsId);
    container.innerHTML = '';
    (items || []).forEach(item => {
      container.appendChild(makeChip(item, removed => {
        currentPrefs[field.key] = (currentPrefs[field.key] || []).filter(v => v !== removed);
      }));
    });
  }

  function setupChipInput(field) {
    const input = document.getElementById(field.inputId);
    if (!input) return;

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        const val = input.value.trim().replace(/,$/, '');
        if (!val) return;
        if (!(currentPrefs[field.key] || []).includes(val)) {
          currentPrefs[field.key] = [...(currentPrefs[field.key] || []), val];
          const container = document.getElementById(field.chipsId);
          container.appendChild(makeChip(val, removed => {
            currentPrefs[field.key] = currentPrefs[field.key].filter(v => v !== removed);
          }));
        }
        input.value = '';
      }
    });
  }

  FIELDS.forEach(setupChipInput);

  // ── Load preferences ───────────────────────────────────────────────────────

  async function load() {
    const prefs = await getPreferences();
    currentPrefs = {
      default_keywords:     [...(prefs.default_keywords     || [])],
      blacklist_terms:      [...(prefs.blacklist_terms      || [])],
      daily_goal:          prefs.daily_goal || 10,
      exclude_already_seen: !!prefs.exclude_already_seen,
      energy_max_reviews:  prefs.energy_max_reviews || 50,
    };

    document.getElementById('pref-daily-goal').value = currentPrefs.daily_goal;
    document.getElementById('pref-exclude-seen').checked = currentPrefs.exclude_already_seen;
    document.getElementById('pref-energy-max').value = currentPrefs.energy_max_reviews;

    FIELDS.forEach(field => populateChips(field, currentPrefs[field.key]));
  }

  // ── Save ────────────────────────────────────────────────────────────────

  document.getElementById('save-btn').addEventListener('click', async () => {
    const toSave = {
      default_keywords:     currentPrefs.default_keywords,
      blacklist_terms:      currentPrefs.blacklist_terms,
      daily_goal:          parseInt(document.getElementById('pref-daily-goal').value, 10) || 10,
      exclude_already_seen: document.getElementById('pref-exclude-seen').checked,
      energy_max_reviews:  parseInt(document.getElementById('pref-energy-max').value, 10) || 0,
    };

    const btn = document.getElementById('save-btn');
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      await savePreferences(toSave);
      showToast('Preferences saved!', 'success');
      // Reload so chips reflect server-normalized values (e.g. "los angeles" → "LA")
      await load();
    } catch (err) {
      showToast('Save failed: ' + err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Save changes';
    }
  });

  load().catch(err => showToast('Failed to load preferences: ' + err.message, 'error'));
})();
