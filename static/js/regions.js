/**
 * regions.js — manage user-defined location regions (LA/NY/BC/ON etc.)
 */
(async function () {
  var regions = [];
  var editMode = {};
  var confirmArm = {};  // regionId -> true after the first Delete click

  var regionsList = document.getElementById('regions-list');
  var addBtn = document.getElementById('add-region-btn');

  async function loadRegions() {
    var res = await fetch('/api/auth/regions');
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).regions || [];
  }

  async function saveRegions(payload) {
    var res = await fetch('/api/auth/regions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).regions;
  }

  async function deleteRegion(regionId) {
    var res = await fetch('/api/auth/regions/' + regionId, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).regions;
  }

  function render() {
    regionsList.innerHTML = '';
    if (regions.length === 0) {
      var empty = document.createElement('p');
      empty.className = 'text-muted regions-empty';
      empty.textContent = 'No regions yet. Click "Add region" to create one.';
      regionsList.appendChild(empty);
      return;
    }
    regions.forEach(function(region) { regionsList.appendChild(makeRegionCard(region)); });
  }

  function makeRegionCard(region) {
    var card = document.createElement('div');
    card.className = 'region-card';
    card.dataset.id = region.id;
    var isEditing = !!editMode[region.id];
    var badge = document.createElement('span');
    badge.className = 'region-badge';
    badge.textContent = region.code;
    badge.style.background = region.color || '#6366f1';

    var header = document.createElement('div');
    header.className = 'region-header';
    var titleRow = document.createElement('div');
    titleRow.className = 'region-title-row';
    titleRow.appendChild(badge);

    var nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'region-name-input';
    nameInput.value = region.name || region.code;
    nameInput.placeholder = 'Display name';
    nameInput.disabled = !isEditing;
    nameInput.dataset.id = region.id;
    titleRow.appendChild(nameInput);

    var headerActions = document.createElement('div');
    headerActions.className = 'region-actions';

    var editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'btn btn--sm btn--ghost region-edit-btn';
    editBtn.textContent = isEditing ? 'Done' : 'Edit';
    editBtn.onclick = function() { toggleEdit(region.id); };
    headerActions.appendChild(editBtn);

    var delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn--sm btn--danger-ghost region-delete-btn';
    delBtn.textContent = 'Delete';
    delBtn.onclick = function() { removeRegion(region.id); };
    headerActions.appendChild(delBtn);

    header.appendChild(titleRow);
    header.appendChild(headerActions);

    var aliasSection = document.createElement('div');
    aliasSection.className = 'region-aliases';
    var aliasLabel = document.createElement('label');
    aliasLabel.className = 'text-muted region-alias-label';
    aliasLabel.textContent = 'Location aliases';
    aliasSection.appendChild(aliasLabel);

    // Render each alias as a chip so the user can see which cities fall under
    // this region (e.g. "ON" -> ["kitchener", "toronto", ...]). Removable in
    // edit mode; new aliases are added with Enter while editing.
    var aliases = region.aliases || [];
    var aliasList = document.createElement('div');
    aliasList.className = 'region-alias-list';

    if (aliases.length === 0) {
      var aliasHint = document.createElement('span');
      aliasHint.className = 'text-muted region-alias-hint';
      aliasHint.textContent = 'No cities mapped yet';
      aliasList.appendChild(aliasHint);
    }
    aliases.forEach(function (alias) {
      var chip = document.createElement('span');
      chip.className = 'chip region-alias-chip';
      chip.textContent = alias;
      if (isEditing) {
        var rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'chip-remove';
        rm.textContent = '×';
        rm.onclick = function () {
          region.aliases = aliases.filter(function (a) { return a !== alias; });
          render();
        };
        chip.appendChild(rm);
      }
      aliasList.appendChild(chip);
    });
    if (isEditing) {
      var aliasInput = document.createElement('input');
      aliasInput.type = 'text';
      aliasInput.className = 'region-alias-input';
      aliasInput.placeholder = 'Type a city and press Enter (e.g. Toronto)';
      aliasInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          var val = aliasInput.value.trim().replace(/,$/, '');
          if (val && !aliases.includes(val)) {
            region.aliases = aliases.concat([val]);
            render();
          }
        }
      });
      aliasList.appendChild(aliasInput);
    }
    aliasSection.appendChild(aliasList);
    card.appendChild(aliasSection);

    // Badge color picker (edit mode only)
    if (isEditing) {
      var colorRow = document.createElement('div');
      colorRow.className = 'region-color-row';
      var colorLabel = document.createElement('label');
      colorLabel.textContent = 'Badge color';
      var colorInput = document.createElement('input');
      colorInput.type = 'color';
      colorInput.className = 'region-color-input';
      colorInput.value = region.color || '#6366f1';
      colorInput.dataset.id = region.id;
      colorInput.addEventListener('input', function () {
        region.color = colorInput.value;
        badge.style.background = colorInput.value;
      });
      colorRow.appendChild(colorLabel);
      colorRow.appendChild(colorInput);
      card.appendChild(colorRow);
    }

    card.appendChild(header);
    return card;
  }

  function toggleEdit(regionId) {
    if (editMode[regionId]) {
      var region = regions.find(function(r) { return r.id === regionId; });
      if (!region) return;
      var ni = document.querySelector('.region-name-input[data-id="' + regionId + '"]');
      if (ni) region.name = ni.value.trim() || region.code;
      var ci = document.querySelector('.region-color-input[data-id="' + regionId + '"]');
      if (ci) region.color = ci.value;
      delete editMode[regionId];
      persistRegions();
    } else {
      editMode[regionId] = true;
      render();
    }
  }

  async function persistRegions() {
    try {
      var payload = { regions: regions.map(function(r) {
        return { id: r.id, code: r.code, name: r.name, color: r.color,
                 sort_order: r.sort_order || 0, enabled: r.enabled !== false ? 1 : 0,
                 aliases: r.aliases || [] };
      })};
      regions = await saveRegions(payload);
      editMode = {};
      render();
      showToast('Regions saved!', 'success');
    } catch (err) {
      showToast('Failed to save regions: ' + err.message, 'error');
    }
  }

  // Two-click delete: the first click arms the button ("Confirm?" for 2.5s);
  // a second click within that window actually deletes via the API.
  async function removeRegion(regionId) {
    var card = document.querySelector('.region-card[data-id="' + regionId + '"]');
    var confirmBtn = card && card.querySelector('.region-delete-btn');
    if (!confirmArm[regionId]) {
      confirmArm[regionId] = true;
      if (confirmBtn) {
        confirmBtn.textContent = 'Confirm?';
        confirmBtn.classList.add('btn--danger');
      }
      setTimeout(function () {
        confirmArm[regionId] = false;
        if (confirmBtn) {
          confirmBtn.textContent = 'Delete';
          confirmBtn.classList.remove('btn--danger');
        }
      }, 2500);
      return;
    }
    try {
      regions = await deleteRegion(regionId);
      delete confirmArm[regionId];
      render();
      showToast('Region deleted.', 'success');
    } catch (err) {
      showToast('Failed to delete region: ' + err.message, 'error');
    }
  }

  function showAddForm() {
    var form = document.getElementById('region-add-form');
    if (form) { form.classList.remove('hidden'); form.querySelector('input').focus(); return; }
    form = document.createElement('div');
    form.id = 'region-add-form';
    form.className = 'region-add-form';
    form.innerHTML =
      '<input type="text" class="region-name-input region-add-code" placeholder="Code (ON)" maxlength="6" />' +
      '<input type="text" class="region-name-input region-add-name" placeholder="Display name (Ontario)" />' +
      '<input type="color" class="region-color-input region-add-color" value="#6366f1" />' +
      '<button type="button" class="btn btn--sm region-add-ok">Add</button>' +
      '<button type="button" class="btn btn--ghost btn--sm region-add-cancel">Cancel</button>';
    regionsList.parentElement.insertBefore(form, regionsList.nextSibling);
    form.querySelector('.region-add-cancel').onclick = function () { form.classList.add('hidden'); };
    form.querySelector('.region-add-ok').onclick = function () {
      var code = (form.querySelector('.region-add-code').value || '').toUpperCase().trim();
      if (!code) return;
      var name = (form.querySelector('.region-add-name').value || '').trim() || code;
      var color = form.querySelector('.region-add-color').value || '#6366f1';
      var newRegion = {
        id: Date.now(), code: code, name: name, color: color,
        sort_order: regions.length, enabled: 1, aliases: [],
      };
      regions = regions.concat([newRegion]);
      editMode[newRegion.id] = true;
      form.classList.add('hidden');
      render();
    };
    form.querySelector('input').focus();
  }

  addBtn.addEventListener('click', showAddForm);

  try {
    regions = await loadRegions();
    render();
  } catch (err) {
    showToast('Failed to load regions: ' + err.message, 'error');
  }
})();
