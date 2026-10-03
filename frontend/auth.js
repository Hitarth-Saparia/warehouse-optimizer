/**
 * frontend/auth.js
 * Client-Side Authentication Controller & Navbar State Manager
 * Connects directly to backend REST endpoints (/api/auth/login, /api/auth/me, /api/auth/logout)
 * Persists HMAC-SHA256 signed bearer tokens and synchronizes user state across all pages.
 */

const AUTH_USER_KEY = 'warehouse_auth_user';
const AUTH_TOKEN_KEY = 'warehouse_auth_token';

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
 * Retrieve current bearer token from localStorage
 */
function getAuthToken() {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY) || null;
  } catch (e) {
    return null;
  }
}

/**
 * Retrieve current user profile object from localStorage
 */
function getAuthUser() {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    console.error('Error reading auth state:', e);
    return null;
  }
}

/**
 * Persist user session (token and user profile)
 */
function setAuthSession(token, user) {
  try {
    if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
    if (user) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
    window.dispatchEvent(new CustomEvent('authchange', { detail: { user, token } }));
  } catch (e) {
    console.error('Error saving auth session:', e);
  }
}

// Backward-compatible alias
function setAuthUser(user) {
  setAuthSession(null, user);
}

/**
 * Clear session from localStorage
 */
function clearAuthSession() {
  try {
    localStorage.removeItem(AUTH_USER_KEY);
    localStorage.removeItem(AUTH_TOKEN_KEY);
    window.dispatchEvent(new CustomEvent('authchange', { detail: { user: null, token: null } }));
  } catch (e) {
    console.error('Error clearing auth session:', e);
  }
}

/**
 * Authenticate with the backend REST API
 */
async function loginUser(email, password) {
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email, password })
    });

    const data = await res.json();

    if (res.ok && data.status === 'success') {
      setAuthSession(data.token, data.user);
      return { success: true, user: data.user, token: data.token };
    } else {
      return {
        success: false,
        error: data.error || 'Authentication failed.',
        status: res.status,
        retryAfter: data.retry_after
      };
    }
  } catch (err) {
    console.error('Network error during login:', err);
    return {
      success: false,
      error: 'Unable to connect to the authentication server. Please ensure the backend is running.'
    };
  }
}

/**
 * Sign out of current session and notify backend
 */
async function logoutUser() {
  const token = getAuthToken();
  if (token) {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
    } catch (e) {
      console.warn('Could not contact logout API endpoint:', e);
    }
  }

  clearAuthSession();

  // If on login page, re-render; otherwise refresh auth components
  if (window.location.pathname.endsWith('login.html')) {
    window.location.reload();
  } else {
    renderNavAuth();
  }
}

/**
 * Authenticated Fetch Wrapper
 * Automatically attaches Authorization header with Bearer token
 */
async function fetchWithAuth(url, options = {}) {
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(url, { ...options, headers });
}

/**
 * Verify active session with backend /api/auth/me
 */
async function verifySession() {
  const token = getAuthToken();
  if (!token) return;

  try {
    const res = await fetch('/api/auth/me', {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (res.status === 401) {
      // Token expired or invalid
      console.warn('Session expired, clearing credentials.');
      clearAuthSession();
      renderNavAuth();
    } else if (res.ok) {
      const data = await res.json();
      if (data.user) {
        setAuthSession(token, data.user);
      }
    }
  } catch (e) {
    // Ignore network glitch during silent check
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
document.addEventListener('DOMContentLoaded', () => {
  renderNavAuth();
  verifySession();
});
window.addEventListener('authchange', renderNavAuth);
