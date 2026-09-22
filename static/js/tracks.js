/**
 * tracks.js — manage user-defined job tracks (regions-style).
 *
 * Each track card holds the display name plus two editable term lists:
 * "Job titles" and "Keywords" — the strings that decide which postings
 * match that track. "not a fit" is reserved and never shown/creatable.
 */
(async function () {
  var tracks = [];
  var editMode = {};    // trackId -> true while that card is in edit mode
  var confirmArm = {};  // trackId -> true after the first Delete click

  var tracksList = document.getElementById('tracks-list');
  var addBtn = document.getElementById('add-track-btn');

  var RESERVED = 'not a fit';

  // ── API helpers ────────────────────────────────────────────────────────────

  async function loadTracks() {
    var res = await fetch('/api/auth/tracks');
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).tracks || [];
  }

  async function saveTracks(payload) {
    var res = await fetch('/api/auth/tracks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).tracks;
  }

  async function deleteTrackRequest(trackId) {
    var res = await fetch('/api/auth/tracks/' + trackId, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()).tracks;
  }

  // Keep the legacy default_tracks preference in sync with the tracks editor,
  // so the review-page filter and daemon see the same names.
  async function syncDefaultTracks(names) {
    await fetch('/api/auth/profile/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ default_tracks: names }),
    });
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  function render() {
    tracksList.innerHTML = '';
    if (tracks.length === 0) {
      var empty = document.createElement('p');
      empty.className = 'text-muted regions-empty';
      empty.textContent = 'No tracks yet. Click "Add track" to create one.';
      tracksList.appendChild(empty);
      return;
    }
    tracks.forEach(function (track) {
      tracksList.appendChild(makeTrackCard(track));
    });
  }

  function trackInitial(track) {
    var name = (track.name || '').trim();
    return name ? name.charAt(0).toUpperCase() : '?';
  }

  function trackColor(track) {
    return track.color || '#4f46e5';
  }

  function buildTermSection(track, kind, label) {
    var section = document.createElement('div');
    section.className = 'region-aliases';

    var sectionLabel = document.createElement('label');
    sectionLabel.className = 'text-muted region-alias-label';
    sectionLabel.textContent = label;
    section.appendChild(sectionLabel);

    var list = document.createElement('div');
    list.className = 'region-alias-list';

    var terms = track[kind] || [];
    if (terms.length === 0) {
      var hint = document.createElement('span');
      hint.className = 'text-muted';
      hint.textContent = 'None yet';
      list.appendChild(hint);
    }
    terms.forEach(function (term) {
      var chip = document.createElement('span');
      chip.className = 'chip region-alias-chip';
      chip.textContent = term;
      if (editMode[track.id]) {
        var rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'chip-remove';
        rm.textContent = '×';
        rm.onclick = function () {
          track[kind] = terms.filter(function (t) { return t !== term; });
          render();
        };
        chip.appendChild(rm);
      }
      list.appendChild(chip);
    });

    if (editMode[track.id]) {
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'region-alias-input';
      input.placeholder = 'Type one and press Enter';
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          var val = input.value.trim().replace(/,$/, '').toLowerCase();
          if (val && !terms.includes(val)) {
            track[kind] = terms.concat([val]);
            render();
          }
        }
      });
      list.appendChild(input);
    }
    section.appendChild(list);
    return section;
  }

  function makeTrackCard(track) {
    var card = document.createElement('div');
    card.className = 'region-card';
    card.dataset.id = track.id;

    var isEditing = !!editMode[track.id];

    var badge = document.createElement('span');
    badge.className = 'region-badge';
    badge.textContent = trackInitial(track);
    badge.style.background = trackColor(track);

    var nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'region-name-input';
    nameInput.value = track.name || '';
    nameInput.placeholder = 'Track name';
    nameInput.disabled = !isEditing;
    nameInput.dataset.id = track.id;

    var titleRow = document.createElement('div');
    titleRow.className = 'region-title-row';
    titleRow.appendChild(badge);
    titleRow.appendChild(nameInput);

    // Display-only: how many postings currently carry this track label.
    // Deleting a track removes only the editor definition; jobs are kept.
    var countEl = document.createElement('span');
    countEl.className = 'text-muted track-count';
    var jobCount = Number(track.job_count || 0);
    countEl.textContent = jobCount + (jobCount === 1 ? ' job' : ' jobs');
    titleRow.appendChild(countEl);

    var editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'btn btn--sm btn--ghost';
    editBtn.textContent = isEditing ? 'Done' : 'Edit';
    editBtn.onclick = function () { toggleEdit(track.id); };

    var delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn--sm btn--danger-ghost region-delete-btn';
    delBtn.textContent = 'Delete';
    delBtn.onclick = function () { removeTrack(track.id, delBtn); };

    var actions = document.createElement('div');
    actions.className = 'region-actions';
    actions.appendChild(editBtn);
    actions.appendChild(delBtn);

    var header = document.createElement('div');
    header.className = 'region-header';
    header.appendChild(titleRow);
    header.appendChild(actions);
    card.appendChild(header);

    // Badge color picker (edit mode only) — mirrors regions.js. Live-preview
    // recolors the badge; the Done handler (toggleEdit) reads the value back
    // into persist. This block must NOT toggle edit state itself — doing so
    // re-rendered the card and looped against the save API on page load.
    if (isEditing) {
      var colorRow = document.createElement('div');
      colorRow.className = 'region-color-row';
      var colorLabel = document.createElement('label');
      colorLabel.textContent = 'Badge color';
      var colorInput = document.createElement('input');
      colorInput.type = 'color';
      colorInput.className = 'region-color-input track-color-input';
      colorInput.value = trackColor(track);
      colorInput.dataset.id = track.id;
      colorInput.addEventListener('input', function () {
        track.color = colorInput.value;
        badge.style.background = colorInput.value;
      });
      colorRow.appendChild(colorLabel);
      colorRow.appendChild(colorInput);
      card.appendChild(colorRow);
    }

    card.appendChild(buildTermSection(track, 'titles', 'Job titles'));
    card.appendChild(buildTermSection(track, 'keywords', 'Keywords'));

    return card;
  }

  // Edit/Done toggle: entering edit re-renders with term inputs and the color
  // picker; leaving edit reads the name/color inputs back into the track and
  // persists. Mirrors regions.js toggleEdit.
  function toggleEdit(trackId) {
    if (editMode[trackId]) {
      var track = tracks.find(function (t) { return t.id === trackId; });
      if (!track) return;
      var ni = document.querySelector('.region-name-input[data-id="' + trackId + '"]');
      if (ni) track.name = ni.value.trim() || track.name;
      var ci = document.querySelector('.track-color-input[data-id="' + trackId + '"]');
      if (ci) track.color = ci.value;
      delete editMode[trackId];
      persistTracks();
    } else {
      editMode[trackId] = true;
      render();
    }
  }

  // Two-click delete: first click arms the button ("Confirm? (keeps N jobs)"
  // for 2.5s); a second click within that window actually deletes via the API.
  // Jobs are NOT removed — only the track definition is deleted.
  function removeTrack(trackId, delBtn) {
    if (!confirmArm[trackId]) {
      var keepCount = 0;
      tracks.forEach(function (t) {
        if (t.id === trackId) { keepCount = Number(t.job_count || 0); }
      });
      confirmArm[trackId] = true;
      delBtn.textContent = keepCount > 0
        ? 'Confirm? (keeps ' + keepCount + (keepCount === 1 ? ' job' : ' jobs') + ')'
        : 'Confirm?';
      delBtn.classList.add('btn--danger');
      setTimeout(function () {
        confirmArm[trackId] = false;
        delBtn.textContent = 'Delete';
        delBtn.classList.remove('btn--danger');
      }, 2500);
      return;
    }
    deleteTrackRequest(trackId).then(function (fresh) {
      tracks = fresh;
      delete confirmArm[trackId];
      render();
      showToast('Track removed. Jobs are kept.', 'success');
      syncDefaultTracks(tracks.map(function (t) { return t.name; })).catch(function () {});
    }).catch(function (err) {
      showToast('Failed to delete track: ' + err.message, 'error');
    });
  }

  async function persistTracks() {
    try {
      var payload = {
        tracks: tracks.map(function (t) {
          return {
            id: t.id,
            name: t.name,
            color: t.color || null,
            sort_order: t.sort_order || 0,
            enabled: t.enabled !== false ? 1 : 0,
            titles: t.titles || [],
            keywords: t.keywords || [],
          };
        }),
      };
      tracks = await saveTracks(payload);
      editMode = {};
      render();
      showToast('Tracks saved!', 'success');
      syncDefaultTracks(tracks.map(function (t) { return t.name; })).catch(function () {});
    } catch (err) {
      showToast('Failed to save tracks: ' + err.message, 'error');
    }
  }

  function showAddForm() {
    var existing = document.getElementById('track-add-form');
    if (existing) {
      existing.classList.remove('hidden');
      existing.querySelector('input').focus();
      return;
    }
    var form = document.createElement('div');
    form.id = 'track-add-form';
    form.className = 'region-add-form';
    form.innerHTML =
      '<input type="text" class="region-name-input track-add-name" placeholder="Track name (e.g. DevOps)" />' +
      '<button type="button" class="btn btn--sm track-add-ok">Add</button>' +
      '<button type="button" class="btn btn--ghost btn--sm track-add-cancel">Cancel</button>';
    tracksList.parentElement.insertBefore(form, tracksList.nextSibling);

    form.querySelector('.track-add-cancel').onclick = function () {
      form.classList.add('hidden');
    };
    form.querySelector('.track-add-ok').onclick = function () {
      var name = (form.querySelector('.track-add-name').value || '').trim();
      if (!name) return;
      if (name.toLowerCase() === RESERVED) {
        showToast('"' + RESERVED + '" is a system track and can\'t be created.', 'error');
        return;
      }
      if (tracks.some(function (t) { return t.name.toLowerCase() === name.toLowerCase(); })) {
        showToast('Track "' + name + '" already exists.', 'error');
        return;
      }
      tracks = tracks.concat([{
        id: Date.now(), name: name, color: '#4f46e5',
        sort_order: tracks.length, enabled: 1,
        titles: [], keywords: [],
      }]);
      editMode[tracks[tracks.length - 1].id] = true;
      form.classList.add('hidden');
      render();
    };
    form.querySelector('input').focus();
  }

  addBtn.addEventListener('click', showAddForm);

  try {
    tracks = await loadTracks();
    render();
  } catch (err) {
    showToast('Failed to load tracks: ' + err.message, 'error');
  }
})();