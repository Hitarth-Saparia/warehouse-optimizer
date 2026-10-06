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
 * Password Criteria Validator
 * Enforces: Min 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special character
 */
function validatePasswordCriteria(password) {
  const pwd = password || '';
  const rules = {
    minLength: pwd.length >= 8,
    hasUpper: /[A-Z]/.test(pwd),
    hasLower: /[a-z]/.test(pwd),
    hasNumber: /[0-9]/.test(pwd),
    hasSpecial: /[!@#$%^&*(),.?":{}|<>\-_+=\[\]\\;'/`~]/.test(pwd)
  };

  const allValid = rules.minLength && rules.hasUpper && rules.hasLower && rules.hasNumber && rules.hasSpecial;

  let error = null;
  if (!rules.minLength) {
    error = 'Password must be at least 8 characters long.';
  } else if (!rules.hasUpper) {
    error = 'Password must include at least one uppercase letter (A-Z).';
  } else if (!rules.hasLower) {
    error = 'Password must include at least one lowercase letter (a-z).';
  } else if (!rules.hasNumber) {
    error = 'Password must include at least one number (0-9).';
  } else if (!rules.hasSpecial) {
    error = 'Password must include at least one special character (!@#$%^&* etc.).';
  }

  return { isValid: allValid, rules, error };
}

/**
 * Register a new user account into the backend database (with local dataset fallback)
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

  // Enforce password criteria on client before dispatch
  const check = validatePasswordCriteria(password);
  if (!check.isValid) {
    return { success: false, error: check.error };
  }

  // Disallow collision with standard demo accounts
  for (const key of Object.keys(DEMO_ACCOUNTS)) {
    if (DEMO_ACCOUNTS[key].email.toLowerCase() === normalizedEmail) {
      return { success: false, error: 'This email is reserved for demo profiles. Please sign in or use another email.' };
    }
  }

  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: trimmedName,
        email: normalizedEmail,
        role: selectedRole,
        password: password
      })
    });

    const data = await res.json();

    if (res.ok && data.status === 'success') {
      setAuthSession(data.token, data.user);
      return { success: true, user: data.user, token: data.token, message: data.message };
    } else {
      return {
        success: false,
        code: data.code || 'REGISTRATION_FAILED',
        error: data.error || 'Failed to create account. Please try again.'
      };
    }
  } catch (err) {
    console.warn('Backend register endpoint error, falling back to local dataset:', err);
  }

  // Local dataset fallback if backend is offline
  const users = getRegisteredUsers();
  if (users.some(u => (u.email || '').toLowerCase() === normalizedEmail)) {
    return { success: false, error: 'An account with this email already exists in the dataset.' };
  }

  const rolePerms = {
    supervisor: { can_modify_layout: false, can_manage_fleet: false, can_pick_orders: true, can_view_audit: false, can_manage_corridors: true },
    fleet: { can_modify_layout: false, can_manage_fleet: true, can_pick_orders: true, can_view_audit: false, can_manage_corridors: false },
    manager: { can_modify_layout: true, can_manage_fleet: true, can_pick_orders: true, can_view_audit: true, can_manage_corridors: true },
    guest: { can_modify_layout: false, can_modify_fleet: false, can_pick_orders: false, can_view_audit: false, can_manage_corridors: false }
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

  const sessionToken = 'token_registered_' + newUser.id + '_' + Date.now();
  setAuthSession(sessionToken, newUser);
  return { success: true, user: newUser, token: sessionToken };
}

/**
 * Retrieve current bearer token from sessionStorage or localStorage
 */
function getAuthToken() {
  try {
    return sessionStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem(AUTH_TOKEN_KEY) || null;
  } catch (e) {
    return null;
  }
}

/**
 * Retrieve current user profile object from sessionStorage or localStorage
 */
function getAuthUser() {
  try {
    const raw = sessionStorage.getItem(AUTH_USER_KEY) || localStorage.getItem(AUTH_USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    console.error('Error reading auth state:', e);
    return null;
  }
}

/**
 * Persist user session.
 * Stores primarily in sessionStorage so the session stays alive across pages
 * and refreshes, and terminates cleanly when the website / browser tab is closed.
 */
function setAuthSession(token, user, rememberMe = false) {
  try {
    if (token) {
      sessionStorage.setItem(AUTH_TOKEN_KEY, token);
      if (rememberMe) localStorage.setItem(AUTH_TOKEN_KEY, token);
    }
    if (user) {
      sessionStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
      if (rememberMe) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
    }
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
 * Clear session from both sessionStorage and localStorage
 */
function clearAuthSession() {
  try {
    sessionStorage.removeItem(AUTH_USER_KEY);
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
    localStorage.removeItem(AUTH_TOKEN_KEY);
    window.dispatchEvent(new CustomEvent('authchange', { detail: { user: null, token: null } }));
  } catch (e) {
    console.error('Error clearing auth session:', e);
  }
}

/**
 * Authenticate with the backend REST API.
 * Distinguishes between non-existent account and wrong password.
 */
async function loginUser(email, password, rememberMe = false) {
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
      setAuthSession(data.token, data.user, rememberMe);
      return { success: true, user: data.user, token: data.token };
    }

    // Backend returned 404 (ACCOUNT_NOT_FOUND) or 401 (INVALID_PASSWORD)
    return {
      success: false,
      status: res.status,
      code: data.code || (res.status === 404 ? 'ACCOUNT_NOT_FOUND' : 'INVALID_PASSWORD'),
      retryAfter: data.retry_after,
      error: data.error || 'Authentication failed.'
    };
  } catch (err) {
    console.warn('Backend login endpoint unavailable, checking registered dataset:', err);
  }

  // Check dataset of newly registered accounts if backend is offline
  const localUsers = getRegisteredUsers();
  const emailMatch = localUsers.find(
    u => (u.email || '').toLowerCase() === normalizedEmail
  );

  if (!emailMatch) {
    return {
      success: false,
      code: 'ACCOUNT_NOT_FOUND',
      error: 'No account found with this email. Please create an account first!'
    };
  }

  if (emailMatch.password !== password) {
    return {
      success: false,
      code: 'INVALID_PASSWORD',
      error: 'Incorrect password. Please verify and try again.'
    };
  }

  const userProfile = {
    id: emailMatch.id,
    name: emailMatch.name,
    email: emailMatch.email,
    role: emailMatch.role,
    initials: emailMatch.initials,
    permissions: emailMatch.permissions,
    created_at: emailMatch.created_at
  };
  const sessionToken = 'token_registered_' + emailMatch.id + '_' + Date.now();
  setAuthSession(sessionToken, userProfile, rememberMe);
  return { success: true, user: userProfile, token: sessionToken };
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
 * Role-Based Access Configuration for App Navigation
 * Defines which pages are accessible for each character/role:
 * - Manager: All pages visible
 * - Picker Lead (Supervisor): Layout Optimizer & Fleet Balancing hidden
 * - Fleet Lead: Products, Layout Optimizer & Order Picking hidden
 * - Guest / Analyst: Read-only views, Layout Optimizer & Fleet Balancing hidden
 */
const ROLE_ALLOWED_PAGES = {
  manager: [
    'landing.html',
    'index.html',
    'products.html',
    'layout.html',
    'graph.html',
    'order-picking.html',
    'waves.html',
    'fleet.html'
  ],
  supervisor: [
    'landing.html',
    'index.html',
    'products.html',
    'graph.html',
    'order-picking.html',
    'waves.html'
  ],
  fleet: [
    'landing.html',
    'index.html',
    'graph.html',
    'waves.html',
    'fleet.html'
  ],
  guest: [
    'landing.html',
    'index.html',
    'products.html',
    'graph.html',
    'order-picking.html',
    'waves.html'
  ]
};

function getUserRoleKey(user) {
  if (!user) return null;
  if (isManagerUser(user)) return 'manager';
  if (isPickerLeadUser(user)) return 'supervisor';
  if (isFleetUser(user)) return 'fleet';
  const role = String(user.role || '').toLowerCase();
  if (ROLE_ALLOWED_PAGES[role]) return role;
  return 'guest';
}

function isPageAllowedForUser(pageHrefOrName, user) {
  if (!user) return true; // Default visible for unauthenticated preview
  const roleKey = getUserRoleKey(user);
  if (!roleKey || !ROLE_ALLOWED_PAGES[roleKey]) return true;

  const cleanName = pageHrefOrName.split('?')[0].split('#')[0].split('/').pop();
  if (!cleanName || cleanName === 'landing.html') return true;

  return ROLE_ALLOWED_PAGES[roleKey].includes(cleanName);
}

/**
 * Determine whether Fleet Balancing should be visible/accessible
 * (Maintained for backward compatibility)
 */
function shouldShowFleetNav(user) {
  return isPageAllowedForUser('fleet.html', user);
}

/**
 * Update role-based navigation item visibility.
 * Toggles navbar links based on the active user role.
 */
function updateNavRoleVisibility() {
  const user = getAuthUser();
  const navLinks = document.querySelectorAll('.nav-links a');

  navLinks.forEach(link => {
    const href = link.getAttribute('href') || '';
    if (href.startsWith('#') || href.includes('login.html')) {
      return;
    }
    const pageName = href.split('?')[0].split('#')[0].split('/').pop();
    if (!pageName) return;

    const isAllowed = isPageAllowedForUser(pageName, user);
    const parentLi = link.closest('li') || link;

    if (isAllowed) {
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
 * If an authenticated user tries to navigate directly to a page unauthorized for their role, redirect to index.html.
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

  // Prevent unauthorized access to pages hidden for this user's role
  if (user && isProtected && !isPageAllowedForUser(page, user)) {
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
