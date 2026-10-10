/**
 * frontend/theme.js
 * Dark/Light Mode Theme Controller for Warehouse Optimizer
 * Persists theme in localStorage, supports system preferences, coordinates canvas redraws,
 * and maintains consistent icon state across all topbar and landing buttons.
 */

(function () {
  const STORAGE_KEY = 'warehouse_optimizer_theme';
  let savedTheme = null;
  try {
    savedTheme = localStorage.getItem(STORAGE_KEY) || localStorage.getItem('wo-theme');
  } catch (e) {}
  
  if (savedTheme === 'dark' || savedTheme === 'light') {
    document.documentElement.setAttribute('data-theme', savedTheme);
  } else if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();

function isDarkMode() {
  return typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark';
}

function toggleTheme() {
  if (typeof document === 'undefined') return;
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  setTheme(next);
}

function setTheme(theme) {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', theme);
  try {
    localStorage.setItem('warehouse_optimizer_theme', theme);
    localStorage.setItem('wo-theme', theme);
  } catch (e) {}
  updateThemeToggleButtons();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
  }
}

const SUN_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';

const MOON_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>';

function updateThemeToggleButtons() {
  if (typeof document === 'undefined') return;
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const isDark = current === 'dark';
  document.querySelectorAll('#theme, .theme-toggle-btn').forEach(btn => {
    btn.setAttribute('aria-label', isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode');
    btn.setAttribute('title', isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode');
    btn.innerHTML = isDark ? SUN_SVG : MOON_SVG;
  });
}

function initThemeButtons() {
  if (typeof document === 'undefined') return;
  document.querySelectorAll('#theme, .theme-toggle-btn').forEach(btn => {
    if (btn._themeInitialized) return;
    btn._themeInitialized = true;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      toggleTheme();
    });
  });
  updateThemeToggleButtons();
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initThemeButtons);
  } else {
    initThemeButtons();
  }
}

// Watch for OS theme changes if user hasn't set an explicit preference
if (typeof window !== 'undefined' && window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    try {
      if (!localStorage.getItem('warehouse_optimizer_theme') && !localStorage.getItem('wo-theme')) {
        setTheme(e.matches ? 'dark' : 'light');
      }
    } catch (err) {}
  });
}
