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
 * Ensure Profile Settings Modal DOM exists on the page
 */
function ensureProfileSettingsModal() {
  if (document.getElementById('profile-settings-modal')) return;
  const container = document.createElement('div');
  container.innerHTML = `
<div class="profile-modal-backdrop" id="profile-settings-modal" onclick="if(event.target === this) closeProfileSettingsModal()">
  <div class="profile-modal-window">
    
    <!-- Modal Header -->
    <div class="profile-modal-header">
      <div class="profile-modal-user-identity">
        <div class="profile-modal-avatar" id="modal-user-avatar">AM</div>
        <div>
          <div style="display: flex; align-items: center;">
            <span class="profile-modal-name" id="modal-user-name">Alex Morgan</span>
            <span class="profile-modal-role-pill" id="modal-user-role">OPERATIONS MANAGER</span>
          </div>
          <div style="font-size: 0.74rem; color: var(--text-secondary); margin-top: 2px;">
            <span>ID: WMS-MGR-0841</span> • <span>Facility: MegaHub Alpha (SFO-01)</span> • <span>Department: Logistics Operations</span>
          </div>
        </div>
      </div>
      <button type="button" class="profile-modal-close-btn" onclick="closeProfileSettingsModal()" aria-label="Close modal" title="Close">
        ✕
      </button>
    </div>

    <!-- Modal Tabs -->
    <div class="profile-modal-tabs" role="tablist">
      <button type="button" class="profile-tab-btn active" data-tab="earnings" onclick="switchProfileModalTab('earnings')">
        💼 Compensation &amp; Live Earnings
      </button>
      <button type="button" class="profile-tab-btn" data-tab="settings" onclick="switchProfileModalTab('settings')">
        ⚙️ Profile &amp; Notification Settings
      </button>
      <button type="button" class="profile-tab-btn" data-tab="security" onclick="switchProfileModalTab('security')">
        🔒 Security &amp; Credentials
      </button>
    </div>

    <!-- Modal Body -->
    <div class="profile-modal-body">

      <!-- TAB 1: MANAGER COMPENSATION & LIVE EARNINGS -->
      <div id="tab-content-earnings" style="display: block;">
        <div style="margin-bottom: 1.25rem;">
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
            <div>
              <h3 style="font-size: 1.05rem; font-weight: 700; margin: 0;">
                Manager Compensation &amp; Performance Dividend
              </h3>
              <div style="font-size: 0.76rem; color: var(--text-secondary); margin-top: 2px;">
                Real-time earnings synchronized with warehouse distance reduction and fulfillment ROI
              </div>
            </div>
            <span class="tag" style="background: rgba(94,122,82,0.18); color: var(--good); font-size: 0.75rem; padding: 0.35rem 0.65rem;">
              Tier 1 Multiplier (1.42x)
            </span>
          </div>
        </div>

        <!-- Earnings Summary Scorecard -->
        <div class="earnings-scorecard-grid">
          <div class="earnings-card highlight">
            <div class="earnings-card-label">Current Month Gross (MTD)</div>
            <div class="earnings-card-amount" id="earnings-mtd-gross" style="color: var(--warn);">$10,615.00</div>
            <div style="font-size: 0.72rem; color: var(--warn); margin-top: 4px;">Base Salary + Optimization Bonus</div>
          </div>

          <div class="earnings-card">
            <div class="earnings-card-label">Base Monthly Salary</div>
            <div class="earnings-card-amount" id="earnings-base-salary">$8,750.00</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 4px;">$105,000 / yr contract</div>
          </div>

          <div class="earnings-card">
            <div class="earnings-card-label">Optimization Bonus (MTD)</div>
            <div class="earnings-card-amount" id="earnings-mtd-bonus" style="color: var(--good);">+$1,865.00</div>
            <div style="font-size: 0.72rem; color: var(--good); margin-top: 4px;">Tied to 39.1% distance saved</div>
          </div>

          <div class="earnings-card">
            <div class="earnings-card-label">Year-to-Date (YTD) Total</div>
            <div class="earnings-card-amount" id="earnings-ytd-total">$94,850.00</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 4px;">9 pay cycles completed</div>
          </div>
        </div>

        <!-- Incentive Breakdown -->
        <div style="margin-bottom: 1.25rem;">
          <h4 style="font-size: 0.88rem; font-weight: 700; margin-bottom: 0.75rem;">
            Monthly Incentive &amp; Performance Commission Breakdown
          </h4>
          <div class="incentive-breakdown-list">
            <div class="incentive-item">
              <div class="incentive-info">
                <span class="incentive-title">📦 Slotting Walking Distance Reduction Bonus</span>
                <span class="incentive-desc">Earned for surpassing enterprise 20% walking reduction benchmark (Current: 39.1% saved = +19.1% surplus)</span>
              </div>
              <span class="incentive-amount" id="incentive-slotting-amount">+$650.00</span>
            </div>

            <div class="incentive-item">
              <div class="incentive-info">
                <span class="incentive-title">⏱️ Order Dispatch SLA On-Time Fulfillment Multiplier</span>
                <span class="incentive-desc">99.4% orders dispatched within same-shift SLA target (Exceeds 98% tier requirement)</span>
              </div>
              <span class="incentive-amount">+$480.00</span>
            </div>

            <div class="incentive-item">
              <div class="incentive-info">
                <span class="incentive-title">🚜 Multi-Picker Fleet Workload Equalization (mTSP)</span>
                <span class="incentive-desc">Greedy wave balancing maintained picker tour variance under 15% across all shifts</span>
              </div>
              <span class="incentive-amount">+$420.00</span>
            </div>

            <div class="incentive-item">
              <div class="incentive-info">
                <span class="incentive-title">🛡️ Safety &amp; Zero Corridor Incident Compliance</span>
                <span class="incentive-desc">Zero safety violations, clear corridor operations, and instant obstacle rerouting</span>
              </div>
              <span class="incentive-amount">+$315.00</span>
            </div>
          </div>
        </div>

        <!-- Live Bonus Simulator -->
        <div class="earnings-simulator-box" style="background: var(--soft); border: 1px solid var(--border-color); border-radius: 12px; padding: 1rem; margin-bottom: 1.25rem;">
          <div class="simulator-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
            <div>
              <strong style="font-size: 0.92rem;">⚡ Live Bonus Simulator</strong>
              <div style="font-size: 0.75rem; color: var(--text-secondary);">Adjust warehouse optimization performance to project next payout:</div>
            </div>
            <div style="text-align: right;">
              <div style="font-size: 0.7rem; color: var(--text-secondary); text-transform: uppercase;">Projected Total Gross</div>
              <div style="font-size: 1.25rem; font-weight: 800; color: var(--warn); font-family: var(--font-mono);" id="sim-projected-gross">$10,615.00</div>
            </div>
          </div>

          <div class="simulator-slider-group" style="margin-bottom: 0.75rem;">
            <div class="simulator-slider-label" style="display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 0.35rem;">
              <span>Warehouse Walking Distance Saved (%)</span>
              <span id="sim-dist-val" style="font-weight: 700; color: var(--good);">39.1% Distance Saved</span>
            </div>
            <input type="range" class="simulator-slider" id="sim-dist-slider" min="15" max="55" step="0.5" value="39.1" oninput="updateBonusSimulator()" style="width: 100%; accent-color: var(--primary);">
          </div>

          <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.78rem; padding-top: 0.5rem; border-top: 1px solid var(--border-color);">
            <span>Projected Optimization Incentive: <strong id="sim-projected-bonus" style="color: var(--good);">+$1,865.00</strong></span>
            <span style="color: var(--text-secondary);">Tied to WMS Pareto Slotting Algorithms</span>
          </div>
        </div>

        <!-- Payout History -->
        <div>
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.65rem;">
            <h4 style="font-size: 0.88rem; font-weight: 700; margin: 0;">Recent Paystubs &amp; Payout History</h4>
            <span style="font-size: 0.74rem; color: var(--text-secondary);">Next Deposit: Oct 15, 2026 (Chase •••• 4821)</span>
          </div>

          <div class="table-responsive">
            <table class="paystub-table" style="width: 100%; font-size: 0.82rem;">
              <thead>
                <tr>
                  <th>Pay Period</th>
                  <th>Base Salary</th>
                  <th>Bonus</th>
                  <th>Gross Pay</th>
                  <th>Net Deposited</th>
                  <th>Status</th>
                  <th>Receipt</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Sep 1 – Sep 30, 2026</strong></td>
                  <td>$8,750.00</td>
                  <td style="color: var(--good);">+$1,865.00</td>
                  <td style="font-weight: 700;">$10,615.00</td>
                  <td>$8,280.00</td>
                  <td><span class="st" style="--c:var(--good)">✓ Paid</span></td>
                  <td><button type="button" class="btn" style="padding: 3px 8px; font-size: 0.72rem;" onclick="downloadPaystub('Sep 2026')">PDF</button></td>
                </tr>
                <tr>
                  <td><strong>Aug 1 – Aug 31, 2026</strong></td>
                  <td>$8,750.00</td>
                  <td style="color: var(--good);">+$1,720.00</td>
                  <td style="font-weight: 700;">$10,470.00</td>
                  <td>$8,166.00</td>
                  <td><span class="st" style="--c:var(--good)">✓ Paid</span></td>
                  <td><button type="button" class="btn" style="padding: 3px 8px; font-size: 0.72rem;" onclick="downloadPaystub('Aug 2026')">PDF</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- TAB 2: PROFILE & NOTIFICATION SETTINGS -->
      <div id="tab-content-settings" style="display: none;">
        <form id="profile-settings-form" onsubmit="saveManagerProfileSettings(event)">
          <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 1rem;">
            Personal &amp; Facility Operational Information
          </h4>

          <div class="profile-form-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem;">
            <div class="profile-field-group">
              <label class="profile-field-label" for="profile-input-name" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">Full Name</label>
              <input type="text" id="profile-input-name" class="profile-field-input" value="Alex Morgan" required style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
            </div>

            <div class="profile-field-group">
              <label class="profile-field-label" for="profile-input-email" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">Email Address</label>
              <input type="email" id="profile-input-email" class="profile-field-input" value="admin@warehouse.io" required style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
            </div>

            <div class="profile-field-group">
              <label class="profile-field-label" for="profile-input-phone" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">Phone Number</label>
              <input type="tel" id="profile-input-phone" class="profile-field-input" value="+1 (555) 392-8411" style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
            </div>

            <div class="profile-field-group">
              <label class="profile-field-label" for="profile-input-facility" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">Assigned Distribution Facility</label>
              <input type="text" id="profile-input-facility" class="profile-field-input" value="MegaHub Alpha (SFO-01)" style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
            </div>

            <div class="profile-field-group" style="grid-column: 1 / -1;">
              <label class="profile-field-label" for="profile-input-shift" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">Preferred Operational Shift</label>
              <select id="profile-input-shift" class="profile-field-input" style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
                <option value="Day Shift (07:00 - 15:30 PST)" selected>Day Shift (07:00 – 15:30 PST) — Core Slotting &amp; Picking</option>
                <option value="Evening Shift (15:30 - 23:30 PST)">Evening Shift (15:30 – 23:30 PST) — Fleet Wave Allocation</option>
                <option value="Night Shift (23:30 - 07:30 PST)">Night Shift (23:30 – 07:30 PST) — Restocking &amp; Heavy Transit</option>
              </select>
            </div>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 0.75rem;">
            <button type="button" class="btn" onclick="closeProfileSettingsModal()">Cancel</button>
            <button type="submit" class="btn primary">💾 Save Profile Changes</button>
          </div>
        </form>
      </div>

      <!-- TAB 3: SECURITY & ACCESS CREDENTIALS -->
      <div id="tab-content-security" style="display: none;">
        <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 1rem;">
          Security &amp; Password Settings
        </h4>
        <div class="profile-form-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem;">
          <div class="profile-field-group">
            <label class="profile-field-label" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">Current Password</label>
            <input type="password" class="profile-field-input" placeholder="••••••••••••" style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
          </div>
          <div class="profile-field-group">
            <label class="profile-field-label" style="display: block; font-size: 0.78rem; font-weight: 600; margin-bottom: 4px;">New Password</label>
            <input type="password" class="profile-field-input" placeholder="Min. 8 chars, 1 uppercase, 1 symbol" style="width: 100%; padding: 8px 12px; border-radius: 8px; border: 1.5px solid var(--border-color); background: var(--card-bg); color: var(--text-main);">
          </div>
        </div>
        <div style="display: flex; justify-content: flex-end;">
          <button type="button" class="btn primary" onclick="showToastNotification('✓ Password successfully updated!')">🔒 Update Credentials</button>
        </div>
      </div>
    </div>
  </div>
</div>`;
  if (document.body) {
    document.body.appendChild(container.firstElementChild);
  }
}

/**
 * Open the Profile Settings & Earnings modal
 */
function openProfileSettingsModal(initialTab = 'earnings') {
  ensureProfileSettingsModal();
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
