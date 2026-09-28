/**
 * frontend/theme.js
 * Dark/Light Mode Theme Controller for Warehouse Optimizer
 * Persists theme in localStorage, supports system preferences, and coordinates canvas redraws.
 */

(function () {
  const STORAGE_KEY = 'warehouse_optimizer_theme';
  const savedTheme = localStorage.getItem(STORAGE_KEY);
  
  if (savedTheme === 'dark' || savedTheme === 'light') {
    document.documentElement.setAttribute('data-theme', savedTheme);
  } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();

function isDarkMode() {
  return document.documentElement.getAttribute('data-theme') === 'dark';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  setTheme(next);
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('warehouse_optimizer_theme', theme);
  updateThemeToggleButtons();
  window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
}

function updateThemeToggleButtons() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const isDark = current === 'dark';
  document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
    btn.setAttribute('aria-label', isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode');
    btn.setAttribute('title', isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode');
  });
}

// Watch for OS theme changes if user hasn't set an explicit preference
if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    if (!localStorage.getItem('warehouse_optimizer_theme')) {
      setTheme(e.matches ? 'dark' : 'light');
    }
  });
}

document.addEventListener('DOMContentLoaded', updateThemeToggleButtons);
