/**
 * frontend/auth.js
 * Client-Side Authentication Controller & Navbar State Manager
 * Connects directly to backend REST endpoints (/api/auth/login, /api/auth/me, /api/auth/logout)
 * Persists HMAC-SHA256 signed bearer tokens and synchronizes user state across all pages.
 */

const AUTH_USER_KEY = 'warehouse_auth_user';
const AUTH_TOKEN_KEY = 'warehouse_auth_token';
const AUTH_REGISTERED_USERS_KEY = 'warehouse_registered_users';

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
 * Retrieve registered accounts stored in the local dataset
 */
function getRegisteredUsers() {
  try {
    const raw = localStorage.getItem(AUTH_REGISTERED_USERS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error('Error reading registered users dataset:', e);
    return [];
  }
}

/**
 * Register a new user account into the dataset
 * Supports seamless frontend onboarding and persists locally
 */
async function registerUser(name, email, role, password) {
  const normalizedEmail = (email || '').trim().toLowerCase();
  const trimmedName = (name || '').trim();
  const selectedRole = (role || 'supervisor').toLowerCase();

  if (!trimmedName) {
    return { success: false, error: 'Full name is required.' };
  }
  if (!normalizedEmail || !normalizedEmail.includes('@')) {
    return { success: false, error: 'A valid email address is required.' };
  }
  if (!password || password.length < 6) {
    return { success: false, error: 'Password must be at least 6 characters.' };
  }

  // Check against demo accounts to prevent collision
  for (const key of Object.keys(DEMO_ACCOUNTS)) {
    if (DEMO_ACCOUNTS[key].email.toLowerCase() === normalizedEmail) {
      return { success: false, error: 'This email is reserved for demo profiles. Please use another email.' };
    }
  }

  // Check if account already exists in registered dataset
  const users = getRegisteredUsers();
  if (users.some(u => (u.email || '').toLowerCase() === normalizedEmail)) {
    return { success: false, error: 'An account with this email already exists in the dataset.' };
  }

  const rolePerms = {
    supervisor: { can_modify_layout: false, can_manage_fleet: false, can_pick_orders: true, can_view_audit: false, can_manage_corridors: true },
    fleet: { can_modify_layout: false, can_manage_fleet: true, can_pick_orders: true, can_view_audit: false, can_manage_corridors: false },
    manager: { can_modify_layout: true, can_manage_fleet: true, can_pick_orders: true, can_view_audit: true, can_manage_corridors: true },
    guest: { can_modify_layout: false, can_manage_fleet: false, can_pick_orders: false, can_view_audit: false, can_manage_corridors: false }
  };

  const parts = trimmedName.split(/\s+/);
  const initials = parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : trimmedName.slice(0, 2).toUpperCase();

  const newUser = {
    id: 'user_' + Date.now(),
    name: trimmedName,
    email: normalizedEmail,
    role: selectedRole,
    initials: initials || 'U',
    password: password,
    permissions: rolePerms[selectedRole] || rolePerms.supervisor,
    created_at: new Date().toISOString()
  };

  users.push(newUser);
  try {
    localStorage.setItem(AUTH_REGISTERED_USERS_KEY, JSON.stringify(users));
  } catch (e) {
    return { success: false, error: 'Storage quota exceeded while saving account to dataset.' };
  }

  return { success: true, user: newUser };
}

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
 * Authenticate with the backend REST API with fallback to the local registered accounts dataset
 */
async function loginUser(email, password) {
  const normalizedEmail = (email || '').trim().toLowerCase();

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email: normalizedEmail, password })
    });

    const data = await res.json();

    if (res.ok && data.status === 'success') {
      setAuthSession(data.token, data.user);
      return { success: true, user: data.user, token: data.token };
    }
  } catch (err) {
    console.warn('Backend login endpoint unavailable, checking registered dataset:', err);
  }

  // Check dataset of newly registered accounts
  const localUsers = getRegisteredUsers();
  const match = localUsers.find(
    u => (u.email || '').toLowerCase() === normalizedEmail && u.password === password
  );

  if (match) {
    const userProfile = {
      id: match.id,
      name: match.name,
      email: match.email,
      role: match.role,
      initials: match.initials,
      permissions: match.permissions,
      created_at: match.created_at
    };
    const sessionToken = 'token_registered_' + match.id + '_' + Date.now();
    setAuthSession(sessionToken, userProfile);
    return { success: true, user: userProfile, token: sessionToken };
  }

  return {
    success: false,
    error: 'Invalid email or password.'
  };
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
 * Role Evaluation Helpers
 */
function isPickerLeadUser(user) {
  if (!user) return false;
  const role = String(user.role || '').toLowerCase();
  const email = String(user.email || '').toLowerCase();
  const name = String(user.name || '').toLowerCase();

  return (
    role === 'supervisor' ||
    role.includes('lead') ||
    role.includes('picker') ||
    email.startsWith('supervisor@') ||
    name.includes('elena')
  );
}

function isFleetUser(user) {
  if (!user) return false;
  const role = String(user.role || '').toLowerCase();
  const email = String(user.email || '').toLowerCase();
  const name = String(user.name || '').toLowerCase();

  return (
    role === 'fleet' ||
    role.includes('fleet') ||
    email.startsWith('fleet@') ||
    name.includes('david chen')
  );
}

function isManagerUser(user) {
  if (!user) return false;
  const role = String(user.role || '').toLowerCase();
  const email = String(user.email || '').toLowerCase();

  return (
    role === 'manager' ||
    role.includes('admin') ||
    role.includes('manager') ||
    email.startsWith('admin@')
  );
}

/**
 * Determine whether Fleet Balancing should be visible/accessible
 * - Picker Lead: Fleet option is NOT visible
 * - Fleet Login: Fleet option IS visible
 * - Manager Login: Fleet option IS visible
 */
function shouldShowFleetNav(user) {
  if (!user) return true; // Default visible for unauthenticated preview
  if (isPickerLeadUser(user)) {
    return false; // Specifically hidden for Picker Lead / supervisor
  }
  if (isFleetUser(user) || isManagerUser(user)) {
    return true; // Shown for Fleet login & Operations Manager
  }
  if (user.permissions && typeof user.permissions.can_manage_fleet === 'boolean') {
    return user.permissions.can_manage_fleet;
  }
  return false;
}

/**
 * Update role-based navigation item visibility.
 * Toggles the "Fleet Balancing" navigation link depending on active user role.
 */
function updateNavRoleVisibility() {
  const user = getAuthUser();
  const showFleet = shouldShowFleetNav(user);

  const fleetLinks = document.querySelectorAll(
    '.nav-links a[href*="fleet.html"], .nav-links a[href="fleet.html"]'
  );

  fleetLinks.forEach(link => {
    const parentLi = link.closest('li') || link;
    if (showFleet) {
      parentLi.style.removeProperty('display');
      parentLi.classList.remove('nav-hidden');
    } else {
      parentLi.style.setProperty('display', 'none', 'important');
      parentLi.classList.add('nav-hidden');
    }
  });
}

/**
 * Dynamically render login button or user profile pill in the navbar
 */
function renderNavAuth() {
  // Synchronize role navigation links
  updateNavRoleVisibility();

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

/**
 * Protected feature pages requiring active user login
 */
const PROTECTED_FEATURE_PAGES = [
  'index.html',
  'products.html',
  'layout.html',
  'graph.html',
  'order-picking.html',
  'waves.html',
  'fleet.html'
];

/**
 * Enforce Route Access Control:
 * If accessing a protected feature page without login, redirect to login.html.
 * If a Picker Lead tries to navigate directly to fleet.html, redirect to index.html.
 */
function checkPageProtection() {
  const path = window.location.pathname;
  let page = path.split('/').pop();
  if (!page || page === '') return;

  const isProtected = PROTECTED_FEATURE_PAGES.some(p => page.endsWith(p));
  const user = getAuthUser();

  if (isProtected && !user) {
    const target = encodeURIComponent(page);
    window.location.href = `login.html?redirect=${target}&login_required=1`;
    return;
  }

  // Prevent unauthorized access to fleet balancing
  if (user && page.endsWith('fleet.html') && !shouldShowFleetNav(user)) {
    window.location.href = 'index.html';
  }
}

// Auto-run on DOM load and listen for changes
document.addEventListener('DOMContentLoaded', () => {
  checkPageProtection();
  renderNavAuth();
  updateNavRoleVisibility();
  verifySession();
});

window.addEventListener('authchange', () => {
  renderNavAuth();
  updateNavRoleVisibility();
});

if (document.readyState === 'interactive' || document.readyState === 'complete') {
  updateNavRoleVisibility();
}
