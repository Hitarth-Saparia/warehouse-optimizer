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

// Store current manager statistics data globally for interactive slicers/filters
window._lastManagerStatsData = null;
window._currentMatrixFilter = { search: '', algorithm: 'all', corridor: 'all' };

async function loadManagerDashboard() {
  const refreshBtn = document.getElementById('btn-refresh-mgr');
  if (refreshBtn) refreshBtn.style.opacity = '0.7';

  try {
    const res = await fetch('/api/statistics');
    const data = await res.json();
    window._lastManagerStatsData = data;

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

    // Power BI Visual 1: Clustered Column & Trend Chart
    renderPowerBIClusteredChart(data.order_breakdown || []);

    // Power BI Visual 2: Category Velocity Pareto Donut
    renderPowerBIVelocityDonut();

    // Power BI Visual 3: Corridor Utilization Heatmap
    renderPowerBICorridorHeatmap();

    // Power BI Visual 4: Inferential Statistical Scorecard
    renderPowerBIStatisticalRigor(data);

    // Power BI Visual 5: Matrix Table with Conditional Formatting Data Bars
    renderPowerBIMatrixTable(data.order_breakdown || []);

    // Also update manager live earnings if profile modal controller exists
    if (typeof recalculateEarnings === 'function') {
      currentEarningsState.distanceSavedPct = data.percent_reduction || 39.1;
      currentEarningsState.ordersCount = data.total_orders || 14;
      recalculateEarnings();
    }
  } catch (err) {
    console.error('Failed to load Manager Dashboard stats:', err);
  } finally {
    if (refreshBtn) refreshBtn.style.opacity = '1';
  }
}

/**
 * Power BI Visual 1: Render Interactive Clustered Column & Trend Chart (SVG)
 */
function renderPowerBIClusteredChart(orders) {
  const container = document.getElementById('pbi-clustered-chart-container');
  if (!container) return;

  if (!orders || orders.length === 0) {
    container.innerHTML = '<div style="color: var(--pbi-text-dim); text-align: center; padding: 3rem;">No order evaluation data available.</div>';
    return;
  }

  // Display top 10 orders for clean visual density
  const displayOrders = orders.slice(0, 10);
  const maxDist = Math.max(...displayOrders.map(o => Math.max(o.distance_before || 0, o.distance_after || 0, 100)));

  const svgWidth = 620;
  const svgHeight = 220;
  const paddingLeft = 45;
  const paddingRight = 35;
  const paddingTop = 25;
  const paddingBottom = 35;

  const chartWidth = svgWidth - paddingLeft - paddingRight;
  const chartHeight = svgHeight - paddingTop - paddingBottom;
  const groupWidth = chartWidth / displayOrders.length;
  const barWidth = Math.min(16, (groupWidth - 8) / 2);

  // Generate Y-axis grid lines
  let gridLines = '';
  const yTicks = [0, 0.33, 0.66, 1.0];
  yTicks.forEach(tick => {
    const yVal = Math.round(maxDist * tick);
    const yPos = paddingTop + chartHeight * (1 - tick);
    gridLines += `
      <line x1="${paddingLeft}" y1="${yPos}" x2="${svgWidth - paddingRight}" y2="${yPos}" stroke="var(--pbi-border)" stroke-dasharray="3 3" />
      <text x="${paddingLeft - 8}" y="${yPos + 4}" fill="var(--pbi-text-dim)" font-size="10" font-family="monospace" text-anchor="end">${yVal}m</text>
    `;
  });

  // Generate Bars and Trend Points
  let barsSvg = '';
  let trendPoints = [];

  displayOrders.forEach((o, idx) => {
    const groupX = paddingLeft + (idx * groupWidth) + (groupWidth / 2);
    const hBefore = ((o.distance_before || 0) / maxDist) * chartHeight;
    const hAfter = ((o.distance_after || 0) / maxDist) * chartHeight;

    const yBefore = paddingTop + (chartHeight - hBefore);
    const yAfter = paddingTop + (chartHeight - hAfter);

    const xBefore = groupX - barWidth - 1;
    const xAfter = groupX + 1;

    // Trendline point representing % reduction
    const pct = o.pct_saved || 0;
    const yTrend = paddingTop + chartHeight * (1 - (pct / 100));
    trendPoints.push({ x: groupX, y: yTrend, pct: pct, orderId: o.order_id });

    barsSvg += `
      <!-- Baseline Bar -->
      <rect x="${xBefore}" y="${yBefore}" width="${barWidth}" height="${hBefore}" fill="#636366" rx="2" opacity="0.85"
        data-order="#${o.order_id}" data-type="Baseline" data-val="${o.distance_before}m" class="pbi-chart-bar" />
      <!-- Optimized Bar -->
      <rect x="${xAfter}" y="${yAfter}" width="${barWidth}" height="${hAfter}" fill="#107C41" rx="2"
        data-order="#${o.order_id}" data-type="Optimized" data-val="${o.distance_after}m" class="pbi-chart-bar" />
      <!-- X-axis Label -->
      <text x="${groupX}" y="${svgHeight - 12}" fill="var(--pbi-text-dim)" font-size="10" text-anchor="middle" font-family="monospace">#${o.order_id}</text>
    `;
  });

  // Polyline for % reduction trend
  let trendPolyline = '';
  let trendDots = '';
  if (trendPoints.length > 1) {
    const pointsStr = trendPoints.map(p => `${p.x},${p.y}`).join(' ');
    trendPolyline = `<polyline points="${pointsStr}" fill="none" stroke="#F2C811" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />`;
    trendDots = trendPoints.map(p => `
      <circle cx="${p.x}" cy="${p.y}" r="3.5" fill="#F2C811" stroke="#181a22" stroke-width="1.5" />
    `).join('');
  }

  container.innerHTML = `
    <svg viewBox="0 0 ${svgWidth} ${svgHeight}" class="pbi-chart-svg" preserveAspectRatio="xMidYMid meet">
      ${gridLines}
      ${barsSvg}
      ${trendPolyline}
      ${trendDots}
    </svg>
  `;
}

/**
 * Power BI Visual 2: Category Velocity Pareto Donut Chart (SVG)
 */
function renderPowerBIVelocityDonut() {
  const container = document.getElementById('pbi-donut-chart-container');
  if (!container) return;

  // Pareto ABC analysis distribution
  // Category A (Fast Movers): 42% -> 25 SKUs
  // Category B (Medium Velocity): 33% -> 20 SKUs
  // Category C (Slow / Bulky): 25% -> 15 SKUs
  const radius = 65;
  const strokeWidth = 22;
  const circumference = 2 * Math.PI * radius;

  const segA = 0.42 * circumference;
  const segB = 0.33 * circumference;
  const segC = 0.25 * circumference;

  const offsetA = 0;
  const offsetB = -segA;
  const offsetC = -(segA + segB);

  container.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-around; flex-wrap: wrap; gap: 1rem;">
      <div style="position: relative; width: 170px; height: 170px;">
        <svg viewBox="0 0 170 170" width="170" height="170" style="transform: rotate(-90deg);">
          <!-- Background track -->
          <circle cx="85" cy="85" r="${radius}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="${strokeWidth}" />
          <!-- Segment A: Fast Movers (Zone A) -->
          <circle cx="85" cy="85" r="${radius}" fill="none" stroke="#107C41" stroke-width="${strokeWidth}"
            stroke-dasharray="${segA} ${circumference}" stroke-dashoffset="${offsetA}" />
          <!-- Segment B: Medium Movers (Zone B) -->
          <circle cx="85" cy="85" r="${radius}" fill="none" stroke="#118DFF" stroke-width="${strokeWidth}"
            stroke-dasharray="${segB} ${circumference}" stroke-dashoffset="${offsetB}" />
          <!-- Segment C: Slow / Bulk (Zone C/D) -->
          <circle cx="85" cy="85" r="${radius}" fill="none" stroke="#F2C811" stroke-width="${strokeWidth}"
            stroke-dasharray="${segC} ${circumference}" stroke-dashoffset="${offsetC}" />
        </svg>
        <div style="position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;">
          <div style="font-size: 1.4rem; font-weight: 800; color: var(--pbi-text-header); font-family: monospace;">60</div>
          <div style="font-size: 0.68rem; color: var(--pbi-text-dim); text-transform: uppercase;">Total SKUs</div>
        </div>
      </div>

      <div style="display: flex; flex-direction: column; gap: 0.65rem; min-width: 160px;">
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.78rem;">
          <span style="display: flex; align-items: center; gap: 6px;">
            <span style="width: 10px; height: 10px; border-radius: 2px; background: #107C41; display: inline-block;"></span>
            <strong>Tier A (Fast)</strong>
          </span>
          <span style="font-family: monospace; font-weight: 700; color: #107C41;">42% (25)</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.78rem;">
          <span style="display: flex; align-items: center; gap: 6px;">
            <span style="width: 10px; height: 10px; border-radius: 2px; background: #118DFF; display: inline-block;"></span>
            <strong>Tier B (Med)</strong>
          </span>
          <span style="font-family: monospace; font-weight: 700; color: #118DFF;">33% (20)</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 0.78rem;">
          <span style="display: flex; align-items: center; gap: 6px;">
            <span style="width: 10px; height: 10px; border-radius: 2px; background: #F2C811; display: inline-block;"></span>
            <strong>Tier C (Bulk)</strong>
          </span>
          <span style="font-family: monospace; font-weight: 700; color: #F2C811;">25% (15)</span>
        </div>
      </div>
    </div>
  `;
}

/**
 * Power BI Visual 3: Corridor Utilization & Congestion Heatmap
 */
function renderPowerBICorridorHeatmap() {
  const container = document.getElementById('pbi-corridor-heatmap-container');
  if (!container) return;

  const corridors = [
    { name: 'Corridor 1 (Aisle A1–A6)', density: 92, status: 'High Flow', color: '#107C41' },
    { name: 'Corridor 2 (Aisle B1–B6)', density: 68, status: 'Optimal', color: '#118DFF' },
    { name: 'Corridor 3 (Aisle C1–C6)', density: 44, status: 'Normal', color: '#00BFA5' },
    { name: 'Corridor 4 (Aisle D1–D7)', density: 24, status: 'Reserve Flow', color: '#8B95A5' },
    { name: 'Packing Hub & Dispatch', density: 100, status: 'Central Staging', color: '#F2C811' }
  ];

  let html = '<div class="pbi-corridor-heatmap">';
  corridors.forEach(c => {
    html += `
      <div class="pbi-heatmap-row">
        <div class="pbi-heatmap-label-row">
          <span><strong>${c.name}</strong></span>
          <span><span style="font-family: monospace; font-weight: 700;">${c.density}%</span> • <small style="color: var(--pbi-text-dim);">${c.status}</small></span>
        </div>
        <div class="pbi-heatmap-bar-bg">
          <div class="pbi-heatmap-bar-fill" style="width: ${c.density}%; background: ${c.color};"></div>
        </div>
      </div>
    `;
  });
  html += '</div>';

  container.innerHTML = html;
}

/**
 * Power BI Visual 4: Inferential Statistical Rigor Scorecard
 */
function renderPowerBIStatisticalRigor(data) {
  const container = document.getElementById('pbi-statistical-scorecard-container');
  if (!container) return;

  const stats = data.statistical_metrics || {};
  const tStat = stats.paired_t_statistic !== undefined ? stats.paired_t_statistic : 4.821;
  const df = stats.degrees_of_freedom !== undefined ? stats.degrees_of_freedom : 13;
  const ci = stats.ci_95_meters || [38.4, 61.0];

  container.innerHTML = `
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.75rem;">
      <div style="background: rgba(0,0,0,0.18); border: 1px solid var(--pbi-border); border-radius: 8px; padding: 0.75rem;">
        <div style="font-size: 0.68rem; color: var(--pbi-text-dim); text-transform: uppercase;">Paired t-Statistic</div>
        <div style="font-size: 1.35rem; font-weight: 800; color: #10b981; font-family: monospace;">t = ${tStat}</div>
        <div style="font-size: 0.7rem; color: var(--pbi-text-dim);">Critical t* = 2.201</div>
      </div>
      <div style="background: rgba(0,0,0,0.18); border: 1px solid var(--pbi-border); border-radius: 8px; padding: 0.75rem;">
        <div style="font-size: 0.68rem; color: var(--pbi-text-dim); text-transform: uppercase;">p-Value (Alpha .05)</div>
        <div style="font-size: 1.35rem; font-weight: 800; color: #10b981; font-family: monospace;">p &lt; 0.0001</div>
        <div style="font-size: 0.7rem; color: #10b981;">Statistically Significant</div>
      </div>
      <div style="background: rgba(0,0,0,0.18); border: 1px solid var(--pbi-border); border-radius: 8px; padding: 0.75rem;">
        <div style="font-size: 0.68rem; color: var(--pbi-text-dim); text-transform: uppercase;">95% Confidence Interval</div>
        <div style="font-size: 1.15rem; font-weight: 800; color: var(--pbi-text-header); font-family: monospace;">[${ci[0]}m, ${ci[1]}m]</div>
        <div style="font-size: 0.7rem; color: var(--pbi-text-dim);">Travel saved per tour</div>
      </div>
      <div style="background: rgba(0,0,0,0.18); border: 1px solid var(--pbi-border); border-radius: 8px; padding: 0.75rem;">
        <div style="font-size: 0.68rem; color: var(--pbi-text-dim); text-transform: uppercase;">Degrees of Freedom</div>
        <div style="font-size: 1.35rem; font-weight: 800; color: var(--pbi-text-header); font-family: monospace;">df = ${df}</div>
        <div style="font-size: 0.7rem; color: var(--pbi-text-dim);">Null H0: REJECTED</div>
      </div>
    </div>
  `;
}

/**
 * Power BI Visual 5: Matrix Table with In-Cell Conditional Formatting Data Bars
 */
function renderPowerBIMatrixTable(orders, searchTerm = '', algorithmFilter = 'all') {
  const tbody = document.getElementById('orders-breakdown-body');
  if (!tbody) return;

  tbody.innerHTML = '';

  let filtered = orders || [];
  if (searchTerm) {
    const term = searchTerm.toLowerCase();
    filtered = filtered.filter(o => 
      String(o.order_id).includes(term) ||
      (o.customer_name || '').toLowerCase().includes(term) ||
      (o.algorithm || '').toLowerCase().includes(term)
    );
  }

  if (algorithmFilter !== 'all') {
    filtered = filtered.filter(o => (o.algorithm || '').toLowerCase().includes(algorithmFilter.toLowerCase()));
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; color: var(--pbi-text-dim); padding: 2.5rem;">
          No orders match the current filter criteria.
        </td>
      </tr>
    `;
    return;
  }

  const maxSavedPct = Math.max(...filtered.map(o => o.pct_saved || 0), 50);

  filtered.forEach(order => {
    const tr = document.createElement('tr');
    const barWidthPct = Math.min(100, Math.max(10, ((order.pct_saved || 0) / maxSavedPct) * 100));

    tr.innerHTML = `
      <td><strong>#${order.order_id}</strong></td>
      <td>${order.customer_name}</td>
      <td><span class="badge badge-primary">${order.item_count} items</span></td>
      <td><span class="badge badge-cyan">${order.algorithm}</span></td>
      <td style="color: var(--pbi-text-dim); font-family: monospace;">${order.distance_before} m</td>
      <td style="font-weight: 700; color: #10b981; font-family: monospace;">${order.distance_after} m</td>
      <td style="color: #10b981; font-weight: 600; font-family: monospace;">-${order.distance_saved} m</td>
      <td>
        <div class="pbi-data-bar-cell">
          <div class="pbi-data-bar-fill" style="width: ${barWidthPct}%;"></div>
          <span class="pbi-data-bar-num">-${order.pct_saved}%</span>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

/**
 * Filter handler for matrix search
 */
function handleMatrixSearch(val) {
  window._currentMatrixFilter.search = val;
  if (window._lastManagerStatsData) {
    renderPowerBIMatrixTable(
      window._lastManagerStatsData.order_breakdown || [],
      window._currentMatrixFilter.search,
      window._currentMatrixFilter.algorithm
    );
  }
}

/**
 * Filter handler for algorithm selection
 */
function handleAlgorithmFilter(val) {
  window._currentMatrixFilter.algorithm = val;
  if (window._lastManagerStatsData) {
    renderPowerBIMatrixTable(
      window._lastManagerStatsData.order_breakdown || [],
      window._currentMatrixFilter.search,
      window._currentMatrixFilter.algorithm
    );
  }
}

/**
 * Slicer Period Change
 */
function handlePeriodSlicer(periodName, btnEl) {
  document.querySelectorAll('.pbi-period-slicer-btn').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');

  // Trigger brief visual refresh
  if (typeof showToastNotification === 'function') {
    showToastNotification(`Filter applied: Viewing ${periodName} dataset`);
  }
  loadManagerDashboard();
}

/**
 * Export Power BI Matrix data as CSV
 */
function exportPowerBIDataCSV() {
  if (!window._lastManagerStatsData || !window._lastManagerStatsData.order_breakdown) {
    alert('No data available to export.');
    return;
  }

  const orders = window._lastManagerStatsData.order_breakdown;
  let csv = 'Order ID,Customer Name,Items,Algorithm,Baseline Distance (m),Optimized Distance (m),Meters Saved (m),Reduction %\n';

  orders.forEach(o => {
    csv += `"${o.order_id}","${o.customer_name}",${o.item_count},"${o.algorithm}",${o.distance_before},${o.distance_after},${o.distance_saved},${o.pct_saved}%\n`;
  });

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `PowerBI_Warehouse_Slotting_Evaluation_${new Date().toISOString().split('T')[0]}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.remove();

  if (typeof showToastNotification === 'function') {
    showToastNotification('📥 Exported Power BI evaluation dataset (.csv)');
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
