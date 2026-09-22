/**
 * nav.js — real-time refresh of sidebar nav badges.
 * Loaded in base.html so it's available on all pages.
 *
 * Nav groups:
 *   Review      -> Swipe Review, Applications (count: ready to apply)
 *   Follow-up   -> Notifications (alerts), Interviews (upcoming)
 *   Network     -> Contacts, Skills
 *   Insights    -> Analytics, Profile
 * Badge/XP numbers stay in the topbar only — the sidebar links stay clean.
 *
 * Feature: Polls badge counts every 30s for real-time updates while the tab
 * is visible. Pauses when the tab is hidden to conserve resources.
 */
(function () {
  window.refreshNavCounts = refreshNavCounts;

  function setupSidebarToggle() {
    const toggle = document.getElementById('sidebar-toggle');
    const close = document.getElementById('sidebar-close');
    const sidebar = document.getElementById('sidebar');
    if (!toggle || !sidebar) return;

    const setOpen = (isOpen) => {
      sidebar.classList.toggle('open', isOpen);
      toggle.setAttribute('aria-expanded', String(isOpen));
      toggle.setAttribute('aria-label', isOpen ? 'Close navigation panel' : 'Open navigation panel');
      toggle.title = isOpen ? 'Close navigation' : 'Open navigation';
    };

    setOpen(false);

    // One delegated listener: survives any re-render of the button and can
    // never double-fire against a second listener bound to the button itself.
    document.addEventListener('click', (e) => {
      if (e.target.closest('#sidebar-toggle')) setOpen(!sidebar.classList.contains('open'));
      if (e.target.closest('#sidebar-close')) setOpen(false);
    });

    sidebar.addEventListener('click', (e) => {
      if (e.target.closest('a')) setOpen(false);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupSidebarToggle, { once: true });
  } else {
    setupSidebarToggle();
  }

  // Track visible counts to detect changes and trigger animations
  const lastCounts = new Map();

  // Real-time polling — poll every 30s, pause when tab hidden
  const BADGE_POLL_INTERVAL = 30000;
  let pollTimer = null;

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refreshNavCounts, BADGE_POLL_INTERVAL);
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    } else {
      refreshNavCounts();
      startPolling();
    }
  });

  // Initial load after DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      refreshNavCounts();
      setTimeout(startPolling, 3000);
    });
  } else {
    refreshNavCounts();
    setTimeout(startPolling, 3000);
  }

  async function refreshNavCounts() {
    // One fetch per source; sidebar badges and topbar stats share the results.
    const fetchOk = async (url) => {
      try {
        const res = await fetch(url, { credentials: 'same-origin' });
        return res.ok ? await res.json() : null;
      } catch (_) {
        return null;
      }
    };

    const [notif, apps, interviews, badges, stats] = await Promise.all([
      fetchOk('/api/notifications'),
      fetchOk('/api/applications'),
      fetchOk('/api/interviews'),
      fetchOk('/api/auth/profile/badges'),
      fetchOk('/api/auth/profile/stats'),
    ]);

    setBadge('notif-count', notif ? notif.count || 0 : 0);
    setBadge('apps-count', apps ? apps.count || 0 : 0);
    setBadge('interview-count', interviews ? (interviews.interviews || []).length : 0);

    const earnedCount = badges && Array.isArray(badges.earned) ? badges.earned.length : 0;
    const totalPoints = stats && stats.total ? Number(stats.total.total_points) || 0 : 0;
    const streak = stats && stats.streak ? Number(stats.streak.current) || 0 : 0;

    // Topbar stats live in base.html on every page. Previously only swipe.js
    // updated them, so they showed 0 on all other pages — sync them here.
    const topStreak = document.getElementById('topbar-streak');
    if (topStreak) topStreak.textContent = `🔥 ${streak}`;
    const topBadges = document.getElementById('topbar-badges');
    if (topBadges) topBadges.textContent = `🏅 ${earnedCount}`;
    const topPoints = document.getElementById('topbar-points');
    if (topPoints) topPoints.textContent = `⭐ ${totalPoints}`;

    // Also refresh the full badge grid on the badges page (real-time updates)
    if (document.getElementById('badge-grid')) {
      if (typeof window.refreshBadgeCount === 'function') {
        window.refreshBadgeCount().catch(() => {});
      }
    }
  }

  // Update one sidebar badge count with a pulse animation on change.
  function setBadge(id, count) {
    const badge = document.getElementById(id);
    if (!badge) return;
    count = Number(count) || 0;
    const prev = lastCounts.get(id);

    badge.textContent = count > 0 ? String(count) : '';
    lastCounts.set(id, count);

    if (prev !== undefined && prev !== count && count > 0) {
      badge.style.transform = 'scale(1.15)';
      setTimeout(() => { badge.style.transform = ''; }, 350);
    }
  }
})();
