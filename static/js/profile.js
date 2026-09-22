/**
 * profile.js — sub-menu (tab) switching between the Preferences and Badges
 * sections on the Profile page.
 *
 * Supports deep links via URL hash: `#preferences` or `#badges`.
 */
(function () {
  const tabs = Array.from(document.querySelectorAll('.profile-tab'));
  const sections = Array.from(document.querySelectorAll('.profile-section'));
  if (tabs.length === 0 || sections.length === 0) return;

  function showSection(name) {
    const valid = ['preferences', 'badges'].includes(name) ? name : 'preferences';
    tabs.forEach((tab) => {
      const isActive = tab.dataset.section === valid;
      tab.classList.toggle('active', isActive);
      tab.setAttribute('aria-selected', String(isActive));
    });
    sections.forEach((section) => {
      section.classList.toggle('hidden', section.dataset.section !== valid);
    });
  }

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const name = tab.dataset.section;
      showSection(name);
      // Update the hash so the current sub-page is shareable/back-button friendly.
      history.replaceState(null, '', '#' + name);
    });
  });

  // Deep-link support: `#badges` opens the Badges sub-page on load.
  const initial = (location.hash || '').replace(/^#\/?/, '');
  showSection(initial);
})();