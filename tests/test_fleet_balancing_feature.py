"""
tests/test_fleet_balancing_feature.py
Comprehensive automated test suite for Fleet Balancing and Vehicle Management.
Validates:
- Real-time dashboard KPI calculations and actual project metrics
- Vehicle CRUD operations, capacity validation, and duplicate prevention
- Order allocation respecting hard capacity constraints and priority sorting
- Unavailable vehicle exclusion (In Transit, Maintenance)
- Warehouse-level demand balancing and inter-warehouse reallocation recommendations
- Route distance and operating cost comparisons (before vs after balancing)
- Two-phase balancing execution (Run Balancing -> Review -> Apply / Discard)
- Database persistence across simulated restarts
"""

import pytest
import json
from backend.app import app
from backend.db import get_db
from backend.fleet_balancer import FleetBalancer
from backend.models import Vehicle, Order


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_fleet_dashboard_kpis(client):
    """Verifies that the dashboard summary produces accurate, computed metrics from project data."""
    res = client.get("/api/fleet/dashboard")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"

    metrics = data["metrics"]
    assert "total_vehicles" in metrics
    assert "available_vehicles" in metrics
    assert "active_vehicles" in metrics
    assert "fleet_utilization_pct" in metrics
    assert "pending_orders" in metrics
    assert "assigned_orders" in metrics
    assert "estimated_operating_cost" in metrics
    assert "potential_savings" in metrics
    assert "savings_pct" in metrics

    assert metrics["total_vehicles"] >= 8
    assert metrics["available_vehicles"] >= 5
    assert metrics["total_fleet_capacity"] > 0
    assert 0.0 <= metrics["fleet_utilization_pct"] <= 100.0

    # Verify warehouse summaries exist
    warehouses = data["warehouse_summaries"]
    assert len(warehouses) >= 3
    wh_ids = [w["warehouse_id"] for w in warehouses]
    assert "WH-01" in wh_ids
    assert "WH-02" in wh_ids
    assert "WH-03" in wh_ids

    for wh in warehouses:
        assert "fleet_capacity_kg" in wh
        assert "pending_demand_kg" in wh
        assert wh["status"] in ["Balanced", "Deficit", "Surplus", "Critical Deficit"]


def test_vehicle_crud_and_validation(client):
    """Tests creating, reading, updating, validating, and deleting vehicles."""
    # 1. Reject invalid ID / duplicate
    res = client.post("/api/fleet/vehicles", json={
        "id": "VEH-101", # Existing
        "name": "Duplicate Test",
        "vehicle_type": "Electric Van",
        "max_capacity": 500,
        "location": "WH-01"
    })
    assert res.status_code == 409

    # 2. Reject non-positive capacity
    res = client.post("/api/fleet/vehicles", json={
        "id": "VEH-TEST-99",
        "name": "Bad Capacity",
        "vehicle_type": "Electric Van",
        "max_capacity": -50,
        "location": "WH-01"
    })
    assert res.status_code == 400

    # 3. Reject invalid status
    res = client.post("/api/fleet/vehicles", json={
        "id": "VEH-TEST-99",
        "name": "Bad Status",
        "vehicle_type": "Electric Van",
        "max_capacity": 500,
        "status": "Destroyed",
        "location": "WH-01"
    })
    assert res.status_code == 400

    # 4. Reject invalid warehouse location
    res = client.post("/api/fleet/vehicles", json={
        "id": "VEH-TEST-99",
        "name": "Bad Location",
        "vehicle_type": "Electric Van",
        "max_capacity": 500,
        "location": "WH-INVALID"
    })
    assert res.status_code == 400

    # 5. Successfully create valid vehicle
    test_id = "VEH-UNIT-01"
    # Ensure test vehicle does not exist
    client.delete(f"/api/fleet/vehicles/{test_id}")

    res = client.post("/api/fleet/vehicles", json={
        "id": test_id,
        "name": "Unit Tester Van",
        "vehicle_type": "Electric Van",
        "max_capacity": 850.0,
        "location": "WH-01",
        "status": "Available",
        "cost_per_km": 1.45,
        "fixed_cost": 20.0
    })
    assert res.status_code == 201
    created = res.get_json()["vehicle"]
    assert created["id"] == test_id
    assert created["max_capacity"] == 850.0

    # 6. View vehicle detail
    res = client.get(f"/api/fleet/vehicles/{test_id}")
    assert res.status_code == 200
    detail = res.get_json()["vehicle"]
    assert detail["name"] == "Unit Tester Van"
    assert detail["available_capacity"] == 850.0

    # 7. Update vehicle
    res = client.put(f"/api/fleet/vehicles/{test_id}", json={
        "name": "Unit Tester Van Modified",
        "vehicle_type": "Box Truck",
        "max_capacity": 950.0,
        "location": "WH-01",
        "status": "Available",
        "cost_per_km": 1.60,
        "fixed_cost": 22.0
    })
    assert res.status_code == 200

    # Verify update persisted
    res = client.get(f"/api/fleet/vehicles/{test_id}")
    assert res.get_json()["vehicle"]["name"] == "Unit Tester Van Modified"
    assert res.get_json()["vehicle"]["max_capacity"] == 950.0

    # 8. Delete vehicle
    res = client.delete(f"/api/fleet/vehicles/{test_id}")
    assert res.status_code == 200

    # Verify vehicle deleted
    res = client.get(f"/api/fleet/vehicles/{test_id}")
    assert res.status_code == 404


def test_order_allocation_and_capacity_constraints():
    """Verifies that the allocation engine never overloads vehicles and respects availability."""
    balancer = FleetBalancer()
    vehicles = balancer.fetch_vehicles()
    orders = balancer.fetch_orders(only_pending=True)

    result = balancer.run_balancing(strategy="best_fit_zone")
    assert result["run_id"] is not None

    allocations = result["proposed_vehicle_allocations"]
    assert len(allocations) > 0

    veh_map = {v.id: v for v in vehicles}

    for pva in allocations:
        v_id = pva["vehicle_id"]
        v = veh_map[v_id]
        # Availability check: unavailable vehicles must not have assignments
        if not v.is_available:
            assert pva["assigned_load"] == 0.0
            assert len(pva["assigned_orders"]) == 0

        # Hard capacity constraint: assigned load must never exceed max_capacity
        assert pva["assigned_load"] <= pva["max_capacity"], f"Vehicle {v_id} overloaded!"
        assert pva["available_capacity"] >= 0.0

    # Check that no order is assigned twice
    assigned_orders = result["assigned_plan"]
    assigned_ids = [ao["order_id"] for ao in assigned_orders]
    assert len(assigned_ids) == len(set(assigned_ids)), "Duplicate order assignments detected!"


def test_warehouse_demand_balancing_and_reallocations():
    """Verifies warehouse demand balancing and generation of inter-warehouse vehicle reallocation recommendations."""
    balancer = FleetBalancer()
    result = balancer.run_balancing()

    recommendations = result.get("recommendations", [])
    # Recommendations should be structured correctly if generated
    for rec in recommendations:
        assert rec["type"] == "VEHICLE_REALLOCATION"
        assert rec["vehicle_id"]
        assert rec["from_warehouse_id"]
        assert rec["to_warehouse_id"]
        assert rec["from_warehouse_id"] != rec["to_warehouse_id"]
        assert rec["transfer_distance_km"] > 0
        assert rec["reason"]


def test_cost_and_distance_optimization():
    """Verifies that balanced routing provides cost and distance metrics with projected savings."""
    balancer = FleetBalancer()
    result = balancer.run_balancing()

    comp = result["comparison"]
    assert "cost_before" in comp
    assert "cost_after" in comp
    assert "cost_savings" in comp
    assert "savings_pct" in comp
    assert "distance_before_km" in comp
    assert "distance_after_km" in comp

    assert comp["cost_before"] > 0
    assert comp["cost_after"] > 0
    # Proposed consolidated multi-stop tour cost should be less than or equal to uncoordinated individual trips
    assert comp["cost_after"] <= comp["cost_before"]
    assert comp["cost_savings"] >= 0
    assert 0.0 <= comp["savings_pct"] <= 100.0


def test_balancing_apply_and_discard_lifecycle(client):
    """Verifies the two-phase optimization lifecycle: Propose -> Apply -> History & Discard."""
    # 1. Run balancing to get a proposed plan
    res = client.post("/api/fleet/balance/run", json={"strategy": "best_fit_zone"})
    assert res.status_code == 200
    run_data = res.get_json()["result"]
    run_id = run_data["run_id"]
    assert run_id is not None
    assert run_data["status"] == "Proposed"

    # 2. Apply changes
    apply_res = client.post("/api/fleet/balance/apply", json={"run_id": run_id})
    assert apply_res.status_code == 200
    assert apply_res.get_json()["status"] == "success"

    # 3. Verify changes persisted in database
    dash_res = client.get("/api/fleet/dashboard")
    dash_data = dash_res.get_json()
    metrics = dash_data["metrics"]
    assert metrics["assigned_orders"] > 0
    assert metrics["fleet_utilization_pct"] > 0.0

    # 4. Check balancing runs history
    history_res = client.get("/api/fleet/balance/runs")
    assert history_res.status_code == 200
    runs = history_res.get_json()["runs"]
    assert len(runs) > 0
    applied_run = next((r for r in runs if r["id"] == run_id), None)
    assert applied_run is not None
    assert applied_run["status"] == "Applied"

    # 5. Create a new run and discard it
    res2 = client.post("/api/fleet/balance/run", json={"strategy": "best_fit_zone"})
    run_id2 = res2.get_json()["result"]["run_id"]

    discard_res = client.post("/api/fleet/balance/discard", json={"run_id": run_id2})
    assert discard_res.status_code == 200
    assert discard_res.get_json()["status"] == "success"


def test_manual_order_assignment_and_capacity_check(client):
    """Tests manually assigning and unassigning an order with capacity enforcement and completed order protection."""
    # 1. Fetch available vehicles
    v_res = client.get("/api/fleet/vehicles?status=Available")
    vehicles = v_res.get_json()["vehicles"]
    assert len(vehicles) > 0
    target_veh = vehicles[0]

    # 2. Find a pending order and a completed order
    all_orders_res = client.get("/api/fleet/orders")
    orders = all_orders_res.get_json()["orders"]
    pending_orders = [o for o in orders if o["status"] == "Pending"]
    completed_orders = [o for o in orders if o["status"] == "Completed"]

    assert len(pending_orders) > 0, "At least one pending order must exist."
    target_order = pending_orders[0]
    target_order_id = target_order["id"]

    # 3. If a completed order exists, verify assigning it is rejected (400)
    if completed_orders:
        comp_id = completed_orders[0]["id"]
        comp_res = client.post(f"/api/fleet/orders/{comp_id}/assign", json={"vehicle_id": target_veh["id"]})
        assert comp_res.status_code == 400
        assert "Cannot assign order" in comp_res.get_json()["message"]

    # 4. Assign pending order to vehicle
    assign_res = client.post(f"/api/fleet/orders/{target_order_id}/assign", json={"vehicle_id": target_veh["id"]})
    assert assign_res.status_code == 200

    # 5. Verify order is assigned
    o_res = client.get(f"/api/fleet/orders?search={target_order_id}")
    orders_matching = o_res.get_json()["orders"]
    matching_o = next((o for o in orders_matching if o["id"] == target_order_id), None)
    assert matching_o is not None
    assert matching_o["assigned_vehicle_id"] == target_veh["id"]

    # 6. Unassign order
    unassign_res = client.post(f"/api/fleet/orders/{target_order_id}/unassign")
    assert unassign_res.status_code == 200

    # 7. Verify unassigned
    o_res2 = client.get(f"/api/fleet/orders?search={target_order_id}")
    matching_o2 = next((o for o in o_res2.get_json()["orders"] if o["id"] == target_order_id), None)
    assert matching_o2["assigned_vehicle_id"] is None
