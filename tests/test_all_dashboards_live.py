import urllib.request
import json

BASE = "http://127.0.0.1:5050"

def api(path, method="GET", body=None):
    try:
        from backend.app import app
        with app.test_client() as client:
            res = client.open(path, method=method, json=body)
            raw = res.get_data(as_text=True)
            return res.status_code, json.loads(raw) if raw else None
    except Exception:
        url = f"{BASE}{path}"
        headers = {"Content-Type": "application/json"}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read().decode("utf-8")
            return res.status, json.loads(raw) if raw else None

def test_manager_dashboard():
    print("--- 1. Testing Operations Manager Dashboard Running Data ---")
    status, stats = api("/api/statistics")
    assert status == 200, f"Expected 200, got {status}"
    assert "avg_distance_before" in stats, "Missing avg_distance_before"
    assert "avg_distance_after" in stats, "Missing avg_distance_after"
    assert "percent_reduction" in stats, "Missing percent_reduction"
    assert "order_breakdown" in stats, "Missing order_breakdown"
    assert len(stats["order_breakdown"]) > 0, "No orders evaluated in breakdown"
    print(f"  [PASS] Manager KPIs: {stats['percent_reduction']}% reduction across {stats['total_orders']} orders")
    print(f"  [PASS] Average picker transit: {stats['avg_distance_before']}m -> {stats['avg_distance_after']}m")

def test_supervisor_dashboard():
    print("--- 2. Testing Order Picker / Floor Supervisor Dashboard Running Data ---")
    status, orders = api("/api/orders")
    assert status == 200, f"Expected 200, got {status}"
    assert len(orders) > 0, "No orders in queue"
    
    # Check pending order completion
    pending_orders = [o for o in orders if o.get("status") == "Pending"]
    target_id = pending_orders[0]["id"] if pending_orders else orders[0]["id"]
    
    status, comp = api(f"/api/orders/{target_id}/complete", method="POST")
    assert status == 200 and comp.get("status") == "success", "Failed to complete order"
    print(f"  [PASS] Order completion: Order #{target_id} marked as Completed")
    
    # Check low stock alerts
    status, inv = api("/api/inventory/status")
    assert status == 200, "Failed to get inventory status"
    assert "low_stock_items" in inv, "Missing low_stock_items"
    print(f"  [PASS] Inventory alert: {inv['low_stock_count']} low stock items detected")
    
    # Test corridor incident toggle
    status, block = api("/api/warehouse/corridor/block", method="POST", body={"from_shelf": 2, "to_shelf": 8})
    assert status == 200, "Failed to block corridor"
    status, unblock = api("/api/warehouse/corridor/unblock", method="POST", body={"from_shelf": 2, "to_shelf": 8})
    assert status == 200, "Failed to unblock corridor"
    print("  [PASS] Corridor incident simulator: Block and Unblock verified")

def test_fleet_dashboard():
    print("--- 3. Testing Fleet Coordinator Dashboard Running Data ---")
    status, fleet = api("/api/fleet/assign-waves?workers=3&cart_capacity=35")
    assert status == 200 and fleet.get("status") == "success", "Failed to get fleet wave assignment"
    workers = fleet.get("workers", [])
    assert len(workers) == 3, f"Expected 3 workers, got {len(workers)}"
    f_metrics = fleet.get("fleet_metrics", {})
    w_metrics = fleet.get("wave_metrics", {})
    print(f"  [PASS] Active pickers: {len(workers)}, Makespan: {f_metrics.get('makespan_distance')}m")
    print(f"  [PASS] Wave batches: {w_metrics.get('total_waves_formed')}, Capacity: {fleet.get('cart_capacity')} units")

def test_layout_and_routing():
    print("--- 4. Testing Layout Optimizer & Routing Live Engine ---")
    status, opt = api("/api/layout/optimize", method="POST")
    assert status == 200, "Failed to optimize layout"
    assert "proposed_assignments" in opt, "Missing proposed assignments"
    print(f"  [PASS] Layout optimizer: {len(opt['proposed_assignments'])} assignments re-slotted")
    
    # Test layout save
    status, save = api("/api/layout/save", method="POST", body={"assignments": opt["proposed_assignments"][:5]})
    assert status == 200 and save.get("status") == "success", "Failed to save layout"
    print("  [PASS] Layout database persistence (/api/layout/save) succeeded")

    # Test order routing
    status, route = api("/api/orders/1/route", method="POST")
    assert status == 200, "Failed to compute order route"
    print(f"  [PASS] Route engine: Dijkstra/TSP computed tour distance = {route.get('total_distance')}m ({route.get('algorithm')})")

def test_simulation_lifecycle():
    print("--- 5. Testing Live Order Simulation & Cleanup ---")
    status, sim = api("/api/orders/simulate", method="POST")
    assert status == 201, "Failed to simulate order"
    sim_id = sim.get("order_id")
    print(f"  [PASS] Simulated Order #{sim_id} created in real database")
    
    status, reset = api("/api/orders/reset-simulated", method="POST")
    assert status == 200, "Failed to reset simulated orders"
    print(f"  [PASS] Reset simulated orders: {reset.get('deleted_count')} purged, benchmark preserved")

def test_wave_picking_dashboard():
    print("--- 6. Testing Wave Picking Dashboard & Lifecycle ---")
    status, dash = api("/api/waves/dashboard")
    assert status == 200 and dash.get("status") == "success", "Failed to get wave dashboard"
    m = dash.get("metrics", {})
    assert "total_waves" in m and "orders_awaiting_picking" in m
    print(f"  [PASS] Wave Dashboard KPIs: {m.get('total_waves')} waves, {m.get('orders_awaiting_picking')} awaiting picking")

    # Test wave proposal preview
    status, prev = api("/api/waves/preview", method="POST", body={"strategy": "Hybrid", "max_cart_capacity": 35})
    assert status == 200 and prev.get("status") == "success", "Failed to generate proposal preview"
    print(f"  [PASS] Wave Proposal Preview: {len(prev.get('proposal', {}).get('wave_proposals', []))} proposals synthesized")

if __name__ == "__main__":
    print("=== RUNNING FULL LIVE DATA DASHBOARDS TEST SUITE ===")
    test_manager_dashboard()
    test_supervisor_dashboard()
    test_fleet_dashboard()
    test_layout_and_routing()
    test_simulation_lifecycle()
    test_wave_picking_dashboard()
    print("====================================================")
    print("ALL DASHBOARDS AND BACKEND ENDPOINTS PASSED FLAWLESSLY!")
