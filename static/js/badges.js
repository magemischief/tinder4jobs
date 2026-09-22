/**
 * Badges.js — render earned + locked badges for the current user.
 */
(async function () {
  var userData = await requireAuth();
  if (!userData) return; // redirected to /login

  var grid = document.getElementById('badge-grid');
  var subtitle = document.getElementById('badges-subtitle');
  var empty = document.getElementById('badges-empty');
  var tabs = document.querySelectorAll('.badge-tab');

  var badges = { earned: [], locked: [] };
  var currentFilter = 'all';

  function renderBadge(badge, isEarned) {
    var card = document.createElement('div');
    card.className = 'badge-card ' + (isEarned ? 'earned' : 'locked');
    var emoji = document.createElement('div');
    emoji.className = 'badge-emoji';
    emoji.textContent = badge.emoji || '\uD83C\uDFC1';
    var name = document.createElement('div');
    name.className = 'badge-name';
    name.textContent = badge.name;
    var desc = document.createElement('div');
    desc.className = 'badge-desc';
    desc.textContent = badge.description;
    var cat = document.createElement('div');
    cat.className = 'badge-category';
    cat.textContent = badge.category;
    if (isEarned && badge.earned_at) {
      var date = document.createElement('div');
      date.className = 'badge-earned-at';
      date.textContent = 'Earned ' + new Date(badge.earned_at).toLocaleDateString();
      card.appendChild(date);
    }
    card.append(emoji, name, desc, cat);
    return card;
  }

  function render() {
    grid.innerHTML = '';
    var shown = 0;
    if (currentFilter === 'all' || currentFilter === 'earned') {
      badges.earned.forEach(function (b) {
        grid.appendChild(renderBadge(b, true));
        shown++;
      });
    }
    if (currentFilter === 'all' || currentFilter === 'locked') {
      badges.locked.forEach(function (b) {
        grid.appendChild(renderBadge(b, false));
        shown++;
      });
    }
    empty.classList.toggle('hidden', shown > 0);
  }

  // Hide skeleton when badges are loaded
  function hideBadgeSkeleton() {
    hideSkeleton(document.getElementById('badge-skeleton'));
  }

  // updateBadgeDisplay is defined inside the IIFE so it has access to the
  // badge DOM elements (grid, subtitle) via closure.
  function updateBadgeDisplay(data) {
    hideBadgeSkeleton();
    // Accept both the direct API response and a wrapped response for resilience
    // when the profile endpoint shape changes.
    var payload = data && typeof data === 'object' ? data : {};
    badges = {
      earned: Array.isArray(payload.earned) ? payload.earned : [],
      locked: Array.isArray(payload.locked) ? payload.locked : [],
    };
    // No numeric counts shown by design — just render the badge cards.
    if (subtitle) subtitle.textContent = 'Your achievements';
    render();
  }

  // Expose on window so swipe.js can call it when new badges are awarded.
  window.refreshBadgeCount = async function () {
    try {
      var fresh = await getBadges();
      updateBadgeDisplay(fresh);
    } catch (_) {
      // silently ignore refresh errors on non-badge pages
    }
  };

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      tabs.forEach(function (t) { t.classList.remove('active'); });
      tab.classList.add('active');
      currentFilter = tab.dataset.filter;
      render();
    });
  });

  try {
    badges = await getBadges();
    updateBadgeDisplay(badges);
  } catch (err) {
    hideBadgeSkeleton();
    if (subtitle) {
      subtitle.textContent = 'Failed to load badges: ' + err.message;
    }
  }
})();
