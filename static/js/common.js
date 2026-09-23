function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function safeUrl(value) {
  const raw = String(value ?? '').trim();
  return /^https?:\/\//i.test(raw) ? raw : '';
}

// Date-only values represent a local calendar day, not UTC midnight. Parsing
// YYYY-MM-DD directly with Date can display the previous day west of UTC.
function parseLocalDate(value) {
  if (!value) return new Date(NaN);
  const text = String(value);
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T00:00:00` : text);
}

function showToast(message, type = 'info', sticky = false) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));

  if (!sticky) {
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 2600);
  }
  return toast;
}

function clearToasts() {
  const container = document.getElementById('toast-container');
  if (container) container.innerHTML = '';
}

function debounce(fn, delay = 200) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// ── Skeleton loading helpers ───────────────────────────────────────────────────
function showSkeleton(el) {
  if (!el) return;
  el.classList.add('skeleton-visible');
  el.classList.remove('skeleton-hidden');
}

function hideSkeleton(el) {
  if (!el) return;
  el.classList.remove('skeleton-visible');
  el.classList.add('skeleton-hidden');
}

function showSkeletons(selector) {
  document.querySelectorAll(selector).forEach(showSkeleton);
}

function hideSkeletons(selector) {
  document.querySelectorAll(selector).forEach(hideSkeleton);
}

// ── Theme management ────────────────────────────────────────────────────────────
const THEME_KEY = 'jh-theme';
function getTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored) return stored;
  // Fall back to system preference (supports dark-mode browser extensions)
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(THEME_KEY, theme);
  // Persist to server (best-effort)
  try {
    fetch('/api/auth/profile/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme }),
    }).catch(() => {});
  } catch (e) { /* ignore */ }
}
async function initTheme() {
  // Instant paint from local cache, then reconcile with the server (server wins).
  applyTheme(getTheme());
  try {
    const prefs = await fetchJSON('/api/auth/profile/preferences');
    const serverTheme = prefs && prefs.theme;
    if (serverTheme) applyTheme(serverTheme);
  } catch (e) { /* offline — keep cached theme */ }

  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.addEventListener('click', () => {
      applyTheme(getTheme() === 'dark' ? 'light' : 'dark');
    });
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initTheme);
} else {
  initTheme();
}

// ── Live-reload polling (dev only) ──────────────────────────────────────────────
// Polls /_livereload/check every 2s; reloads page when static/template files change.
(function () {
  let lastMtime = 0;
  const checkInterval = 2000;
  let timer = null;

  async function checkForChanges() {
    try {
      const res = await fetch('/_livereload/check', { credentials: 'same-origin' });
      if (!res.ok) return;
      const data = await res.json();
      if (data.enabled === false) {
        if (timer) clearInterval(timer);
        return;
      }
      if (lastMtime && data.mtime > lastMtime) {
        console.log('[LiveReload] Detected file changes, reloading...');
        window.location.reload();
      }
      lastMtime = data.mtime;
    } catch (e) {
      // Ignore errors (e.g., network, 404 in production)
    }
  }

  // Start polling after a brief delay to let the page settle
  setTimeout(() => {
    checkForChanges();
    timer = setInterval(checkForChanges, checkInterval);
  }, 500);
})();
