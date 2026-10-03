/**
 * frontend/auth.js
 * Client-Side Authentication Controller & Navbar State Manager
 * Handles mock session persistence, profile presets, login/logout events,
 * and seamlessly synchronizes the user profile pill across all pages.
 */

const AUTH_STORAGE_KEY = 'warehouse_auth_user';

// Pre-configured demo accounts for quick testing
const DEMO_ACCOUNTS = {
  manager: {
    email: 'admin@warehouse.io',
    name: 'Alex Morgan',
    role: 'Operations Manager',
    initials: 'AM',
    password: 'password123'
  },
  supervisor: {
    email: 'supervisor@warehouse.io',
    name: 'Elena Ramos',
    role: 'Picking Lead',
    initials: 'ER',
    password: 'password123'
  },
  fleet: {
    email: 'fleet@warehouse.io',
    name: 'David Chen',
    role: 'Fleet Coordinator',
    initials: 'DC',
    password: 'password123'
  }
};

/**
 * Retrieve current logged in user from localStorage
 */
function getAuthUser() {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    console.error('Error reading auth state:', e);
    return null;
  }
}

/**
 * Persist user session in localStorage
 */
function setAuthUser(user) {
  try {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user));
    window.dispatchEvent(new CustomEvent('authchange', { detail: { user } }));
  } catch (e) {
    console.error('Error saving auth state:', e);
  }
}

/**
 * Clear user session (Logout)
 */
function logoutUser() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent('authchange', { detail: { user: null } }));
  // If on login page, re-render; otherwise reload or redirect
  if (window.location.pathname.endsWith('login.html')) {
    window.location.reload();
  } else {
    renderNavAuth();
  }
}

/**
 * Dynamically render login button or user profile pill in the navbar
 */
function renderNavAuth() {
  const rightActions = document.querySelector('.nav-right-actions');
  if (!rightActions) return;

  // Remove existing auth elements if already present
  const existingBtn = rightActions.querySelector('#nav-auth-link');
  const existingPill = rightActions.querySelector('#nav-user-pill');
  if (existingBtn) existingBtn.remove();
  if (existingPill) existingPill.remove();

  const user = getAuthUser();
  const isLoginPage = window.location.pathname.endsWith('login.html');

  if (user) {
    // User is logged in: show profile pill
    const pill = document.createElement('div');
    pill.className = 'nav-user-pill';
    pill.id = 'nav-user-pill';
    pill.innerHTML = `
      <div class="nav-user-avatar" title="${user.role}">${user.initials || 'U'}</div>
      <div class="nav-user-info">
        <span class="nav-user-name">${user.name}</span>
        <span class="nav-user-role">${user.role}</span>
      </div>
      <button class="nav-user-logout" title="Sign out of account" aria-label="Sign out" onclick="logoutUser()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
          <polyline points="16 17 21 12 16 7"></polyline>
          <line x1="21" y1="12" x2="9" y2="12"></line>
        </svg>
      </button>
    `;
    rightActions.insertBefore(pill, rightActions.firstChild);
  } else if (!isLoginPage) {
    // User is not logged in and not on login page: show "Sign In" button
    const authBtn = document.createElement('a');
    authBtn.href = 'login.html';
    authBtn.className = 'nav-auth-btn';
    authBtn.id = 'nav-auth-link';
    authBtn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path>
        <polyline points="10 17 15 12 10 7"></polyline>
        <line x1="15" y1="12" x2="3" y2="12"></line>
      </svg>
      <span>Sign In</span>
    `;
    rightActions.insertBefore(authBtn, rightActions.firstChild);
  }
}

// Auto-run on DOM load and listen for changes
document.addEventListener('DOMContentLoaded', renderNavAuth);
window.addEventListener('authchange', renderNavAuth);
