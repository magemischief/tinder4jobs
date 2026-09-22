/**
 * auth.js — client-side auth helpers.
 * Provides login/logout/requireAuth helpers used by all pages.
 */

let _currentUser = null;

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (res.status === 401) {
    // Not logged in — redirect to login
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
    return null;
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function loadCurrentUser() {
  if (_currentUser) return _currentUser;
  const data = await fetchJSON('/api/auth/me');
  if (data === null) return null; // redirected
  _currentUser = data;
  return _currentUser;
}

async function requireAuth() {
  const data = await loadCurrentUser();
  if (data === null) return null; // redirected to login
  return data;
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  _currentUser = null;
  window.location.href = '/login';
}

async function savePreferences(prefs) {
  return fetchJSON('/api/auth/profile/preferences', {
    method: 'POST',
    body: JSON.stringify(prefs),
  });
}

async function getPreferences() {
  return fetchJSON('/api/auth/profile/preferences');
}

async function getStats() {
  return fetchJSON('/api/auth/profile/stats');
}

async function getBadges() {
  return fetchJSON('/api/auth/profile/badges');
}

// Wire up the sidebar logout form
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('logout-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      logout();
    });
  }
});
