/**
 * frontend/profile-settings.js
 * Manager Profile Settings & Compensation/Earnings Controller
 * Supports:
 * - Live dynamic earnings calculation tied to warehouse slotting efficiency
 * - Interactive Bonus Simulator with sliders (distance saved, order volume)
 * - Historical paystub records & payout receipts
 * - Profile information editing (Name, Email, Phone, Shift, Facility, Notifications)
 * - Live session persistence via sessionStorage/localStorage
 */

let activeProfileModalTab = 'earnings';
let currentEarningsState = {
  baseSalary: 8750.00,
  distanceSavedPct: 39.1,
  ordersCount: 14,
  calculatedBonus: 1865.00,
  ytdEarnings: 94850.00
};

/**
 * Open the Profile Settings & Earnings modal
 */
function openProfileSettingsModal(initialTab = 'earnings') {
  const modal = document.getElementById('profile-settings-modal');
  if (!modal) return;

  // Retrieve current user or fallback to manager
  const user = (typeof getAuthUser === 'function' ? getAuthUser() : null) || {
    name: 'Alex Morgan',
    email: 'admin@warehouse.io',
    role: 'Operations Manager',
    initials: 'AM',
    phone: '+1 (555) 392-8411',
    facility: 'MegaHub Alpha (SFO-01)',
    shift: 'Day Shift (07:00 - 15:30 PST)'
  };

  // Populate header identity
  const nameEl = document.getElementById('modal-user-name');
  const roleEl = document.getElementById('modal-user-role');
  const avatarEl = document.getElementById('modal-user-avatar');
  if (nameEl) nameEl.textContent = user.name || 'Alex Morgan';
  if (roleEl) roleEl.textContent = (user.role || 'Operations Manager').toUpperCase();
  if (avatarEl) avatarEl.textContent = user.initials || 'AM';

  // Populate form fields
  const inputName = document.getElementById('profile-input-name');
  const inputEmail = document.getElementById('profile-input-email');
  const inputPhone = document.getElementById('profile-input-phone');
  const inputFacility = document.getElementById('profile-input-facility');
  const inputShift = document.getElementById('profile-input-shift');

  if (inputName) inputName.value = user.name || 'Alex Morgan';
  if (inputEmail) inputEmail.value = user.email || 'admin@warehouse.io';
  if (inputPhone) inputPhone.value = user.phone || '+1 (555) 392-8411';
  if (inputFacility) inputFacility.value = user.facility || 'MegaHub Alpha (SFO-01)';
  if (inputShift) inputShift.value = user.shift || 'Day Shift (07:00 - 15:30 PST)';

  // Sync earnings with current live dashboard metrics if available
  const reductionStatEl = document.getElementById('stat-reduction');
  if (reductionStatEl) {
    const rawPct = parseFloat(reductionStatEl.textContent) || 39.1;
    currentEarningsState.distanceSavedPct = rawPct;
    recalculateEarnings();
  }

  // Switch to requested tab
  switchProfileModalTab(initialTab);

  // Show modal
  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

/**
 * Close the Profile Settings & Earnings modal
 */
function closeProfileSettingsModal() {
  const modal = document.getElementById('profile-settings-modal');
  if (!modal) return;
  modal.classList.remove('active');
  document.body.style.overflow = '';
}

/**
 * Switch tabs in the modal (Earnings vs Settings vs Security)
 */
function switchProfileModalTab(tabName) {
  activeProfileModalTab = tabName;

  document.querySelectorAll('.profile-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  const tabEarnings = document.getElementById('tab-content-earnings');
  const tabSettings = document.getElementById('tab-content-settings');
  const tabSecurity = document.getElementById('tab-content-security');

  if (tabEarnings) tabEarnings.style.display = (tabName === 'earnings') ? 'block' : 'none';
  if (tabSettings) tabSettings.style.display = (tabName === 'settings') ? 'block' : 'none';
  if (tabSecurity) tabSecurity.style.display = (tabName === 'security') ? 'block' : 'none';
}

/**
 * Recalculate manager's live earnings based on warehouse efficiency
 */
function recalculateEarnings() {
  const base = currentEarningsState.baseSalary; // $8,750
  const pct = currentEarningsState.distanceSavedPct; // e.g. 39.1%

  // Tiered incentive calculation:
  // Base bonus: $1,000 for meeting 20% benchmark
  // +$45.00 for every additional 1% distance saved
  const extraPct = Math.max(0, pct - 20);
  const slottingBonus = Math.round(650 + (extraPct * 22));
  const slaBonus = 480;
  const fleetBonus = 420;
  const safetyBonus = 315;

  const totalBonus = slottingBonus + slaBonus + fleetBonus + safetyBonus;
  const totalGross = base + totalBonus;

  currentEarningsState.calculatedBonus = totalBonus;

  // Update DOM elements
  const grossEl = document.getElementById('earnings-mtd-gross');
  const baseEl = document.getElementById('earnings-base-salary');
  const bonusEl = document.getElementById('earnings-mtd-bonus');
  const ytdEl = document.getElementById('earnings-ytd-total');
  const slottingBonusEl = document.getElementById('incentive-slotting-amount');

  if (grossEl) grossEl.textContent = `$${totalGross.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (baseEl) baseEl.textContent = `$${base.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (bonusEl) bonusEl.textContent = `+$${totalBonus.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (ytdEl) ytdEl.textContent = `$${(currentEarningsState.ytdEarnings + totalGross).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (slottingBonusEl) slottingBonusEl.textContent = `+$${slottingBonus.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * Interactive Bonus Simulator slider change
 */
function updateBonusSimulator() {
  const slider = document.getElementById('sim-dist-slider');
  const label = document.getElementById('sim-dist-val');
  const projectedBonusEl = document.getElementById('sim-projected-bonus');
  const projectedGrossEl = document.getElementById('sim-projected-gross');

  if (!slider) return;
  const simulatedPct = parseFloat(slider.value);
  if (label) label.textContent = `${simulatedPct.toFixed(1)}% Distance Saved`;

  const extraPct = Math.max(0, simulatedPct - 20);
  const simulatedSlotting = Math.round(450 + (extraPct * 35));
  const simulatedBonus = simulatedSlotting + 480 + 420 + 315;
  const simulatedGross = currentEarningsState.baseSalary + simulatedBonus;

  if (projectedBonusEl) projectedBonusEl.textContent = `+$${simulatedBonus.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  if (projectedGrossEl) projectedGrossEl.textContent = `$${simulatedGross.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
}

/**
 * Save Manager Profile Settings
 */
function saveManagerProfileSettings(event) {
  if (event) event.preventDefault();

  const name = (document.getElementById('profile-input-name')?.value || 'Alex Morgan').trim();
  const email = (document.getElementById('profile-input-email')?.value || 'admin@warehouse.io').trim();
  const phone = (document.getElementById('profile-input-phone')?.value || '+1 (555) 392-8411').trim();
  const facility = (document.getElementById('profile-input-facility')?.value || 'MegaHub Alpha (SFO-01)').trim();
  const shift = (document.getElementById('profile-input-shift')?.value || 'Day Shift (07:00 - 15:30 PST)').trim();

  // Compute initials
  const initials = name.split(' ').map(p => p[0]).join('').substring(0, 2).toUpperCase() || 'AM';

  // Get current user or create
  let user = (typeof getAuthUser === 'function' ? getAuthUser() : null) || {};
  user = {
    ...user,
    name,
    email,
    phone,
    facility,
    shift,
    initials,
    role: user.role || 'Operations Manager'
  };

  // Persist using existing session helper
  if (typeof setAuthSession === 'function') {
    const token = typeof getAuthToken === 'function' ? getAuthToken() : 'token_local';
    setAuthSession(token, user, true);
  } else {
    sessionStorage.setItem('warehouse_auth_user', JSON.stringify(user));
    localStorage.setItem('warehouse_auth_user', JSON.stringify(user));
  }

  // Update active page displays
  const greetingName = document.getElementById('user-greeting-name');
  const greetingAvatar = document.getElementById('user-greeting-avatar');
  if (greetingName) greetingName.textContent = user.name;
  if (greetingAvatar) greetingAvatar.textContent = user.initials;

  const modalName = document.getElementById('modal-user-name');
  const modalAvatar = document.getElementById('modal-user-avatar');
  if (modalName) modalName.textContent = user.name;
  if (modalAvatar) modalAvatar.textContent = user.initials;

  // Re-render auth pill
  if (typeof renderNavAuth === 'function') {
    renderNavAuth();
  }

  showToastNotification('✓ Manager profile & notification settings saved successfully!');
  closeProfileSettingsModal();
}

/**
 * Download simulated Paystub
 */
function downloadPaystub(periodName) {
  showToastNotification(`📥 Generated official paystub for ${periodName} (PDF Downloaded)`);
}

/**
 * Toast notification banner
 */
function showToastNotification(message) {
  const existing = document.querySelector('.pbi-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'pbi-toast';
  toast.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="20 6 9 17 4 12"></polyline>
    </svg>
    <span>${message}</span>
  `;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    setTimeout(() => toast.remove(), 350);
  }, 3200);
}

// Global keyboard accessibility: Close modal on Esc
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeProfileSettingsModal();
  }
});

// Auto-open modal if URL query param or hash requests it
document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('modal') === 'profile' || window.location.hash === '#profile-settings') {
    setTimeout(() => openProfileSettingsModal(), 200);
  }
});
