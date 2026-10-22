/**
 * frontend/events.js
 * Real-Time Server-Sent Events (SSE) Client & Live Notification Hub.
 * Connects to /api/events and handles live incoming order dispatches and inventory updates.
 */

(function initWarehouseEvents() {
  let eventSource = null;
  let reconnectTimer = null;

  function connectSSE() {
    if (eventSource) {
      eventSource.close();
    }

    eventSource = new EventSource('/api/events');

    eventSource.onopen = function () {
      console.log('[SSE] Live warehouse operational event stream connected.');
      updateLiveBadge(true);
    };

    eventSource.onmessage = function (e) {
      try {
        const payload = JSON.parse(e.data);
        handleWarehouseEvent(payload);
      } catch (err) {
        // Ping or raw message
      }
    };

    eventSource.onerror = function () {
      updateLiveBadge(false);
      if (eventSource) eventSource.close();
      clearTimeout(reconnectTimer);
      // Auto reconnect after 5s
      reconnectTimer = setTimeout(connectSSE, 5000);
    };
  }

  function handleWarehouseEvent(evt) {
    if (!evt || !evt.type) return;

    switch (evt.type) {
      case 'new_order':
        showOrderToast(evt.data);
        triggerOrderListeners(evt.data);
        break;

      case 'order_completed':
        showCompletionToast(evt.data);
        triggerOrderListeners(evt.data);
        break;

      case 'inventory_updated':
        showInventoryToast(evt.data);
        triggerInventoryListeners(evt.data);
        break;

      default:
        break;
    }
  }

  function showOrderToast(order) {
    const toast = document.createElement('div');
    toast.className = 'sse-toast sse-toast-order';
    toast.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 1.3rem;">⚡</span>
        <div>
          <div style="font-weight: 700; font-size: 0.88rem;">New Order #${order.order_id} Dispatched</div>
          <div style="font-size: 0.76rem; opacity: 0.85;">${escapeHtml(order.customer_name)} • ${order.stop_count || '?'} stops</div>
        </div>
      </div>
      <a href="order-picking.html?order_id=${order.order_id}" class="sse-toast-btn">Pick Now</a>
    `;
    displayToast(toast);
  }

  function showCompletionToast(data) {
    const toast = document.createElement('div');
    toast.className = 'sse-toast sse-toast-success';
    toast.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 1.3rem;">✅</span>
        <div>
          <div style="font-weight: 700; font-size: 0.88rem;">Order #${data.order_id} Completed</div>
          <div style="font-size: 0.76rem; opacity: 0.85;">Stock deducted for ${data.items_deducted || 0} line items.</div>
        </div>
      </div>
    `;
    displayToast(toast);
  }

  function showInventoryToast(data) {
    const toast = document.createElement('div');
    toast.className = 'sse-toast sse-toast-info';
    toast.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 1.3rem;">📦</span>
        <div>
          <div style="font-weight: 700; font-size: 0.88rem;">Catalog Updated via CSV</div>
          <div style="font-size: 0.76rem; opacity: 0.85;">${data.imported} added, ${data.updated} updated.</div>
        </div>
      </div>
    `;
    displayToast(toast);
  }

  function displayToast(el) {
    let container = document.getElementById('sse-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'sse-toast-container';
      container.style.cssText = 'position:fixed;bottom:24px;left:24px;z-index:99999;display:flex;flex-direction:column;gap:10px;pointer-events:none;';
      document.body.appendChild(container);
    }
    el.style.pointerEvents = 'auto';
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(10px)';
      setTimeout(() => el.remove(), 400);
    }, 4500);
  }

  function updateLiveBadge(isLive) {
    const badge = document.getElementById('live-stream-badge');
    if (badge) {
      badge.style.display = 'inline-flex';
      badge.innerHTML = isLive
        ? '<span style="width:7px;height:7px;background:#22c55e;border-radius:50%;display:inline-block;animation:pulse 1.5s infinite;"></span> <span style="font-size:0.75rem;font-weight:700;color:#22c55e;">LIVE FEED</span>'
        : '<span style="width:7px;height:7px;background:#ef4444;border-radius:50%;display:inline-block;"></span> <span style="font-size:0.75rem;font-weight:700;color:#ef4444;">OFFLINE</span>';
    }
  }

  function triggerOrderListeners(order) {
    window.dispatchEvent(new CustomEvent('newwarehouseorder', { detail: order }));
    // If on order-picking page and order select exists, append option
    const orderSelect = document.getElementById('order-select');
    if (orderSelect && order && order.order_id) {
      let opt = orderSelect.querySelector(`option[value="${order.order_id}"]`);
      if (!opt) {
        opt = document.createElement('option');
        opt.value = order.order_id;
        opt.textContent = `Order #${order.order_id} - ${order.customer_name} (${order.stop_count || 0} stops)`;
        orderSelect.appendChild(opt);
      }
    }
  }

  function triggerInventoryListeners(data) {
    window.dispatchEvent(new CustomEvent('inventoryupdated', { detail: data }));
    if (typeof loadProducts === 'function') {
      loadProducts();
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    }[m]));
  }

  // Inject SSE Toast Styles
  const style = document.createElement('style');
  style.textContent = `
    .sse-toast {
      background: var(--nav-bg, rgba(67, 51, 42, 0.95));
      color: var(--card, #F7F5E9);
      padding: 10px 16px;
      border-radius: 8px;
      box-shadow: 0 10px 25px rgba(80, 62, 51, 0.35);
      border: 1px solid var(--border-color, rgba(148, 111, 92, 0.35));
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-width: 290px;
      max-width: 400px;
      animation: sseSlideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      transition: all 0.3s ease;
      font-family: var(--font-sans, inherit);
    }
    .sse-toast-order { border-left: 4px solid var(--primary, #A95C64); }
    .sse-toast-success { border-left: 4px solid #10b981; }
    .sse-toast-info { border-left: 4px solid var(--secondary, #C3A697); }
    .sse-toast-btn {
      background: var(--primary, #A95C64);
      color: #fff;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 0.74rem;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
      transition: opacity 0.2s;
    }
    .sse-toast-btn:hover { opacity: 0.9; }
    @keyframes sseSlideIn {
      from { opacity: 0; transform: translateY(15px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);

  // Connect on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', connectSSE);
  } else {
    connectSSE();
  }
})();
