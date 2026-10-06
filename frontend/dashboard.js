/**
 * frontend/dashboard.js
 * Role-Tailored Dynamic Dashboard Controller
 * Provides specialized real-time views for:
 * 1. Operations Manager (Strategic KPIs, Before/After benchmarks, Re-slotting)
 * 2. Picker Lead / Floor Supervisor (Live picking queue, order completion, corridor blockages, low stock)
 * 3. Fleet Lead / Coordinator (mTSP wave allocations, cart balancing, worker workload cards)
 */

let activeDashboardRole = 'manager';
let currentFleetWorkerCount = 3;
let currentFleetCartCapacity = 35;

/**
 * Determine default role on page load based on active authenticated user
 */
function initDashboardRole() {
  const user = getAuthUser();
  if (user) {
    if (isFleetUser(user)) {
      activeDashboardRole = 'fleet';
    } else if (isPickerLeadUser(user)) {
      activeDashboardRole = 'supervisor';
    } else {
      activeDashboardRole = 'manager';
    }
  } else {
    activeDashboardRole = 'manager';
  }

  updateDashboardBannerIdentity(user);
  switchDashboardRole(activeDashboardRole);
}

/**
 * Update the top identity banner
 */
function updateDashboardBannerIdentity(user) {
  const nameEl = document.getElementById('user-greeting-name');
  const roleEl = document.getElementById('user-greeting-role');
  const avatarEl = document.getElementById('user-greeting-avatar');

  if (user) {
    if (nameEl) nameEl.textContent = user.name;
    if (roleEl) roleEl.textContent = user.role.toUpperCase();
    if (avatarEl) avatarEl.textContent = user.initials || 'U';
  } else {
    if (nameEl) nameEl.textContent = 'Warehouse Operator';
    if (roleEl) roleEl.textContent = 'GUEST PREVIEW';
    if (avatarEl) avatarEl.textContent = 'WO';
  }
}

/**
 * Switch dashboard view between Manager, Picker Lead, and Fleet Lead
 */
function switchDashboardRole(role) {
  activeDashboardRole = role;

  // Update tabs in banner
  document.querySelectorAll('.role-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.role === role);
  });

  // Toggle role view containers
  const viewManager = document.getElementById('view-manager');
  const viewSupervisor = document.getElementById('view-supervisor');
  const viewFleet = document.getElementById('view-fleet');

  if (viewManager) viewManager.style.display = (role === 'manager') ? 'block' : 'none';
  if (viewSupervisor) viewSupervisor.style.display = (role === 'supervisor') ? 'block' : 'none';
  if (viewFleet) viewFleet.style.display = (role === 'fleet') ? 'block' : 'none';

  // Load the corresponding data
  if (role === 'manager') {
    loadManagerDashboard();
  } else if (role === 'supervisor') {
    loadSupervisorDashboard();
  } else if (role === 'fleet') {
    loadFleetDashboard();
  }
}

// =====================================================================
// 1. OPERATIONS MANAGER DASHBOARD
// =====================================================================

async function loadManagerDashboard() {
  const refreshBtn = document.getElementById('btn-refresh-mgr');
  if (refreshBtn) refreshBtn.style.opacity = '0.7';

  try {
    const res = await fetch('/api/statistics');
    const data = await res.json();

    // Populate Summary Stats
    const prodEl = document.getElementById('stat-products');
    const shelfEl = document.getElementById('stat-shelves');
    const orderEl = document.getElementById('stat-orders');
    const redEl = document.getElementById('stat-reduction');
    const savedDescEl = document.getElementById('stat-saved-desc');

    if (prodEl) prodEl.textContent = data.total_products || 60;
    if (shelfEl) shelfEl.textContent = data.total_shelves || 25;
    if (orderEl) orderEl.textContent = data.total_orders || 0;
    if (redEl) redEl.textContent = (data.percent_reduction || 0) + '%';
    if (savedDescEl) savedDescEl.textContent = `${data.total_distance_saved || 0} meters total saved`;

    // Populate Comparison Banner
    const bBefore = document.getElementById('banner-before');
    const bAfter = document.getElementById('banner-after');
    const bRed = document.getElementById('banner-reduction');
    const bSaved = document.getElementById('banner-saved');
    const bar = document.getElementById('efficiency-bar');

    if (bBefore) bBefore.textContent = (data.avg_distance_before || 0) + ' m';
    if (bAfter) bAfter.textContent = (data.avg_distance_after || 0) + ' m';
    if (bRed) bRed.textContent = '-' + (data.percent_reduction || 0) + '%';
    if (bSaved) bSaved.textContent = (data.total_distance_saved || 0) + ' m';

    if (bar && data.avg_distance_before > 0) {
      const ratio = (data.avg_distance_after / data.avg_distance_before) * 100;
      bar.style.width = `${Math.min(100, ratio).toFixed(1)}%`;
    }

    // Populate Orders Breakdown Table
    const tbody = document.getElementById('orders-breakdown-body');
    if (tbody && data.order_breakdown) {
      tbody.innerHTML = '';
      data.order_breakdown.forEach(order => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>#${order.order_id}</strong></td>
          <td>${order.customer_name}</td>
          <td><span class="badge badge-primary">${order.item_count} items</span></td>
          <td><span class="badge badge-cyan">${order.algorithm}</span></td>
          <td style="color: #94a3b8;">${order.distance_before} m</td>
          <td style="font-weight: 700; color: #10b981;">${order.distance_after} m</td>
          <td style="color: #10b981;">-${order.distance_saved} m</td>
          <td><span class="badge badge-success">-${order.pct_saved}%</span></td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error('Failed to load Manager Dashboard stats:', err);
  } finally {
    if (refreshBtn) refreshBtn.style.opacity = '1';
  }
}

/**
 * Simulate an Enterprise Customer Order (Manager Quick Action)
 */
async function simulateEnterpriseOrder() {
  const btn = document.getElementById('btn-sim-order');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Simulating Order...';
  }

  try {
    const res = await fetch('/api/orders/simulate', { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      alert(`✓ Simulated Order #${data.order_id} generated for ${data.route?.customer_name || 'Enterprise'}!`);
      loadManagerDashboard();
    } else {
      alert('Order simulation failed: ' + (data.error || 'Server error'));
    }
  } catch (e) {
    alert('Failed to simulate order.');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Simulate Enterprise Order';
    }
  }
}

// =====================================================================
// 2. PICKER LEAD / FLOOR SUPERVISOR DASHBOARD
// =====================================================================

async function loadSupervisorDashboard() {
  const refreshBtn = document.getElementById('btn-refresh-sup');
  if (refreshBtn) refreshBtn.style.opacity = '0.7';

  try {
    // 1. Fetch Orders List
    const resOrders = await fetch('/api/orders');
    const ordersData = await resOrders.json();
    const orders = ordersData.orders || [];

    // Tally queue counts
    const pendingCount = orders.filter(o => (o.status || 'Pending').toLowerCase() === 'pending').length;
    const pickingCount = orders.filter(o => (o.status || '').toLowerCase() === 'picking').length;
    const completedCount = orders.filter(o => (o.status || '').toLowerCase() === 'completed').length;

    const elPending = document.getElementById('sup-stat-pending');
    const elPicking = document.getElementById('sup-stat-picking');
    const elCompleted = document.getElementById('sup-stat-completed');

    if (elPending) elPending.textContent = pendingCount;
    if (elPicking) elPicking.textContent = pickingCount;
    if (elCompleted) elCompleted.textContent = completedCount;

    // 2. Fetch Blocked Corridors
    const resBlocked = await fetch('/api/warehouse/corridors/blocked');
    const blockedData = await resBlocked.json();
    const blockedCount = blockedData.count !== undefined ? blockedData.count : (blockedData.blocked_corridors ? blockedData.blocked_corridors.length : 0);
    const elBlocked = document.getElementById('sup-stat-blocked');
    if (elBlocked) elBlocked.textContent = blockedCount;

    renderCorridorIncidentStatus(blockedData.blocked_corridors || []);

    // 3. Render Live Picking Queue Table
    renderPickingQueueTable(orders);

    // 4. Fetch Low Stock Alerts
    loadLowStockWidget();
  } catch (err) {
    console.error('Failed to load Supervisor dashboard:', err);
  } finally {
    if (refreshBtn) refreshBtn.style.opacity = '1';
  }
}

function renderCorridorIncidentStatus(blockedCorridors) {
  const statusContainer = document.getElementById('corridor-status-widget');
  if (!statusContainer) return;

  if (blockedCorridors.length === 0) {
    statusContainer.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
        <div style="display: flex; align-items: center; gap: 0.65rem;">
          <div class="status-dot"></div>
          <div>
            <strong>All Corridors Clear:</strong> Warehouse aisles are unobstructed and operating at maximum transit speed.
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="toggleSimulatedCorridorBlock(true)">
          🚧 Simulate Aisle Spill Incident (Shelf 2 ↔ 8)
        </button>
      </div>
    `;
  } else {
    const list = blockedCorridors.map(c => {
      const from = c.from_shelf !== undefined ? c.from_shelf : (Array.isArray(c) ? c[0] : (c.from || '?'));
      const to = c.to_shelf !== undefined ? c.to_shelf : (Array.isArray(c) ? c[1] : (c.to || '?'));
      return `Shelf ${from} ↔ Shelf ${to}`;
    }).join(', ');

    statusContainer.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
        <div style="display: flex; align-items: center; gap: 0.65rem;">
          <span style="font-size: 1.2rem;">⚠️</span>
          <div>
            <strong style="color: #ef4444;">Active Corridor Blockage:</strong> ${list}.
            <div style="font-size: 0.78rem; color: #94a3b8;">Dijkstra shortest-paths are automatically rerouting pickers around this section.</div>
          </div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="toggleSimulatedCorridorBlock(false)">
          ✓ Clear Aisle Incident
        </button>
      </div>
    `;
  }
}

async function toggleSimulatedCorridorBlock(shouldBlock) {
  const endpoint = shouldBlock ? '/api/warehouse/corridor/block' : '/api/warehouse/corridor/unblock';
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_shelf: 2, to_shelf: 8, shelf_a: 2, shelf_b: 8 })
    });
    if (res.ok) {
      loadSupervisorDashboard();
    }
  } catch (e) {
    console.error('Error toggling corridor block:', e);
  }
}

function renderPickingQueueTable(orders) {
  const tbody = document.getElementById('supervisor-queue-body');
  if (!tbody) return;

  tbody.innerHTML = '';
  if (orders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-light); padding: 2rem;">No customer orders found.</td></tr>`;
    return;
  }

  orders.slice(0, 15).forEach(order => {
    const status = (order.status || 'Pending').toLowerCase();
    const statusBadge = status === 'completed'
      ? `<span class="badge-status completed">✓ Completed</span>`
      : status === 'picking'
      ? `<span class="badge-status picking">⚡ Picking</span>`
      : `<span class="badge-status pending">⏳ Pending</span>`;

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>#${order.id}</strong></td>
      <td>${order.customer_name}</td>
      <td><span class="badge badge-primary">${order.item_count || (order.items ? order.items.length : 3)} items</span></td>
      <td>${statusBadge}</td>
      <td>
        <a href="order-picking.html?order=${order.id}" class="btn-table-action" title="Compute optimal Dijkstra/TSP tour">
          🗺️ Route Pick Tour
        </a>
      </td>
      <td>
        ${status !== 'completed' ? `
          <button class="btn-table-action btn-table-complete" onclick="markOrderCompleted(${order.id})">
            ✓ Complete Order
          </button>
        ` : `<span style="color: #94a3b8; font-size: 0.78rem;">Fulfilled</span>`}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function markOrderCompleted(orderId) {
  try {
    const res = await fetch(`/api/orders/${orderId}/complete`, { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.status === 'success') {
      loadSupervisorDashboard();
    } else {
      alert('Failed to mark order completed: ' + (data.error || 'Server error'));
    }
  } catch (e) {
    alert('Error completing order.');
  }
}

async function loadLowStockWidget() {
  const container = document.getElementById('low-stock-list');
  if (!container) return;

  try {
    const res = await fetch('/api/inventory/status');
    const data = await res.json();
    const lowStockItems = data.low_stock_items || data.low_stock_products || [];

    if (lowStockItems.length === 0) {
      container.innerHTML = `<div style="color: #10b981; font-size: 0.85rem; padding: 0.5rem 0;">✓ All products are well stocked (> 20 units).</div>`;
      return;
    }

    container.innerHTML = lowStockItems.slice(0, 5).map(item => `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.45rem 0; border-bottom: 1px solid var(--border);">
        <div>
          <strong style="font-size: 0.82rem;">${item.name}</strong>
          <span style="font-size: 0.75rem; color: #94a3b8;"> (Shelf ${item.assigned_shelf_id || 'N/A'})</span>
        </div>
        <span class="badge badge-danger">${item.stock_quantity} left</span>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div style="color: #94a3b8; font-size: 0.8rem;">Stock status unavailable.</div>`;
  }
}

// =====================================================================
// 3. FLEET LEAD / COORDINATOR DASHBOARD
// =====================================================================

async function loadFleetDashboard() {
  const refreshBtn = document.getElementById('btn-refresh-fleet');
  if (refreshBtn) refreshBtn.style.opacity = '0.7';

  try {
    const url = `/api/fleet/assign-waves?workers=${currentFleetWorkerCount}&cart_capacity=${currentFleetCartCapacity}`;
    const res = await fetch(url);
    const data = await res.json();

    if (!res.ok || data.status !== 'success') {
      console.warn('Failed to load fleet allocation:', data.error);
      return;
    }

    // Populate Fleet Metrics Ribbon
    const fMetrics = data.fleet_metrics || {};
    const wMetrics = data.wave_metrics || {};

    const elWorkers = document.getElementById('fleet-stat-workers');
    const elCapacity = document.getElementById('fleet-stat-capacity');
    const elWaves = document.getElementById('fleet-stat-waves');
    const elMakespan = document.getElementById('fleet-stat-makespan');

    if (elWorkers) elWorkers.textContent = fMetrics.active_workers || currentFleetWorkerCount;
    if (elCapacity) elCapacity.textContent = currentFleetCartCapacity;
    if (elWaves) elWaves.textContent = wMetrics.total_waves_formed || 0;
    if (elMakespan) elMakespan.textContent = (fMetrics.makespan_distance || 0) + ' m';

    // Populate Worker Workload Cards
    renderWorkerCards(data.workers || [], fMetrics.makespan_distance || 1);

    // Populate Wave Batches Table
    renderWaveBatchesTable(data.workers || []);
  } catch (err) {
    console.error('Failed to load Fleet Dashboard:', err);
  } finally {
    if (refreshBtn) refreshBtn.style.opacity = '1';
  }
}

function updateFleetParameters() {
  const workerSelect = document.getElementById('fleet-worker-select');
  const capInput = document.getElementById('fleet-cap-input');

  if (workerSelect) currentFleetWorkerCount = parseInt(workerSelect.value, 10) || 3;
  if (capInput) currentFleetCartCapacity = parseInt(capInput.value, 10) || 35;

  loadFleetDashboard();
}

function renderWorkerCards(workers, maxMakespan) {
  const container = document.getElementById('fleet-worker-cards-container');
  if (!container) return;

  container.innerHTML = '';
  workers.forEach(w => {
    const totalDist = w.total_distance || 0;
    const waveCount = (w.assigned_waves || []).length;
    const totalItems = (w.assigned_waves || []).reduce((acc, wave) => acc + (wave.total_units !== undefined ? wave.total_units : (wave.total_items || 0)), 0);
    const ratio = Math.min(100, Math.round((totalDist / maxMakespan) * 100));

    const card = document.createElement('div');
    card.className = 'worker-card';
    card.innerHTML = `
      <div class="worker-card-header">
        <div class="worker-card-name">
          <span>🚜</span>
          <span>${w.worker_name}</span>
        </div>
        <span class="badge ${totalDist >= maxMakespan ? 'badge-warning' : 'badge-success'}">
          ${totalDist >= maxMakespan ? 'Makespan Tour' : 'Balanced'}
        </span>
      </div>

      <div class="worker-card-stats">
        <div>
          <div class="worker-stat-sublabel">Batches</div>
          <div class="worker-stat-subval">${waveCount}</div>
        </div>
        <div>
          <div class="worker-stat-sublabel">Items</div>
          <div class="worker-stat-subval">${totalItems}</div>
        </div>
        <div>
          <div class="worker-stat-sublabel">Distance</div>
          <div class="worker-stat-subval">${totalDist} m</div>
        </div>
      </div>

      <div>
        <div class="worker-progress-header">
          <span>Workload vs Peak Makespan</span>
          <strong>${ratio}%</strong>
        </div>
        <div class="worker-progress-track">
          <div class="worker-progress-fill ${ratio >= 90 ? 'heavy' : 'balanced'}" style="width: ${ratio}%;"></div>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderWaveBatchesTable(workers) {
  const tbody = document.getElementById('fleet-waves-body');
  if (!tbody) return;

  tbody.innerHTML = '';
  workers.forEach(w => {
    (w.assigned_waves || []).forEach(wave => {
      let orderIds = '';
      if (Array.isArray(wave.order_ids)) {
        orderIds = wave.order_ids.map(id => `#${id}`).join(', ');
      } else if (Array.isArray(wave.orders)) {
        orderIds = wave.orders.map(o => `#${o.id || o}`).join(', ');
      }
      const waveLabel = wave.batch_name || ('Wave #' + (wave.batch_id || wave.wave_id || 1));
      const units = wave.total_units !== undefined ? wave.total_units : (wave.total_items || 0);
      const dist = wave.batched_distance !== undefined ? wave.batched_distance : (wave.distance || 0);

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${waveLabel}</strong></td>
        <td><span class="badge badge-cyan">${w.worker_name}</span></td>
        <td>${orderIds || 'N/A'}</td>
        <td>${units} units</td>
        <td>${wave.unique_stops || 0} stops</td>
        <td style="font-weight: 700; color: #10b981;">${dist} m</td>
      `;
      tbody.appendChild(tr);
    });
  });
}

// Auto-initialize when loaded
document.addEventListener('DOMContentLoaded', () => {
  initDashboardRole();
});

window.addEventListener('authchange', () => {
  initDashboardRole();
});
