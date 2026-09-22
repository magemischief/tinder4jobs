/**
 * api.js — single shared fetch client for the Jobhunt frontend.
 * Why: previously every page used raw fetch() with different 401/error
 * handling, and common.js called fetchJSON() defined in auth.js (load-order
 * fragile). All pages should use apiFetch/apiJSON from here instead.
 * load_common.js? no — load order: base.html loads common.js, auth.js,
 * then api.js (this file), so helpers depending on fetchJSON keep working
 * while new code migrates to apiFetch.
 */

async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (res.status === 401) {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
    return null; // redirected
  }
  return res;
}

async function apiJSON(url, options = {}) {
  const res = await apiFetch(url, options);
  if (res === null) return null; // redirected to login
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}
