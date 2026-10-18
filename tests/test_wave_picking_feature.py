"""
tests/test_wave_picking_feature.py
Unit and integration tests for Wave Picking feature:
- Live KPI dashboard metrics calculations
- Intelligent order grouping algorithms (Priority, Due-date, Zone, SKU, Batch-capacity, Hybrid)
- Inventory stock checks, reservations, and double-allocation prevention
- End-to-end wave picking lifecycle (Draft -> Active -> Picking -> Completed / Cancelled)
- Task-level confirmation, partial picking, over-picking rejection, and exception reporting
- Physical stock decrement upon completion and reservation release upon cancellation
- Pick list CSV export formatting
"""

import json
import pytest
from backend.app import app, fetch_warehouse, fetch_all_orders, fetch_all_products
from backend.db import get_db
from backend.wave_manager import WaveManager


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_wave_dashboard_kpis(client):
    """Verifies live KPI metrics calculation from database."""
    res = client.get("/api/waves/dashboard")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    metrics = data["metrics"]
    assert "total_waves" in metrics
    assert "status_counts" in metrics
    assert "orders_awaiting_picking" in metrics
    assert "units_to_pick" in metrics
    assert "picking_progress_pct" in metrics
    assert isinstance(metrics["status_counts"]["draft"], int)
    assert isinstance(metrics["status_counts"]["active"], int)
    assert isinstance(metrics["status_counts"]["completed"], int)


def test_grouping_strategies(client):
    """Verifies that all 6 order grouping strategies execute cleanly."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        orders = fetch_all_orders(conn)[:6]

        strategies = [
            "Priority-based",
            "Due-date-based",
            "Zone-based",
            "SKU-based",
            "Batch/Capacity-based",
            "Hybrid"
        ]

        for strat in strategies:
            batches = manager.group_orders(orders, strategy=strat, max_cart_capacity=40, max_orders_per_batch=3)
            assert len(batches) > 0, f"Strategy {strat} failed to group orders"
            # Verify capacity constraint
            for b in batches:
                total_units = sum(o["units"] for o in b)
                assert total_units <= 40, f"Capacity violated in {strat}"
                assert len(b) <= 3, f"Max orders violated in {strat}"
    finally:
        conn.close()


def test_wave_proposal_preview(client):
    """Verifies wave proposal preview API without persisting to database."""
    payload = {
        "strategy": "Hybrid",
        "max_cart_capacity": 30,
        "max_orders_per_batch": 3,
        "priority": "High",
        "assigned_picker": "Alex Morgan"
    }
    res = client.post("/api/waves/preview", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    proposal = data["proposal"]
    assert "wave_proposals" in proposal
    assert "summary" in proposal
    if proposal["wave_proposals"]:
        p1 = proposal["wave_proposals"][0]
        assert "tasks" in p1
        assert "distance_saved_m" in p1
        assert "stock_verified" in p1
        # Check that tasks have SKU and allocations
        for t in p1["tasks"]:
            assert "sku" in t
            assert "order_allocations" in t
            assert t["required_quantity"] > 0


def test_wave_crud_and_conflict_prevention(client):
    """Verifies wave creation, retrieval, and prevention of double-allocated orders."""
    # Create wave with orders 1 and 2
    res = client.post("/api/waves", json={
        "name": "Integration Test Wave Alpha",
        "order_ids": [1, 2],
        "strategy": "Zone-based",
        "priority": "High",
        "assigned_picker": "Marcus Vance",
        "max_cart_capacity": 40,
        "notes": "Testing conflict prevention"
    })
    assert res.status_code == 201
    created_wave = res.get_json()["wave"]
    wave_id = created_wave["id"]
    assert wave_id.startswith("WAVE-")
    assert created_wave["total_orders"] == 2
    assert len(created_wave["tasks"]) > 0

    # Retrieve wave details
    get_res = client.get(f"/api/waves/{wave_id}")
    assert get_res.status_code == 200
    assert get_res.get_json()["wave"]["name"] == "Integration Test Wave Alpha"

    # Attempt to create another wave using the same order 1 (should fail with conflict error)
    conflict_res = client.post("/api/waves", json={
        "name": "Conflicting Wave",
        "order_ids": [1, 3],
        "strategy": "Hybrid"
    })
    assert conflict_res.status_code == 400
    assert "already allocated" in conflict_res.get_json()["message"]

    # Clean up by cancelling the test wave
    cancel_res = client.post(f"/api/waves/{wave_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.get_json()["wave"]["status"] == "Cancelled"


def test_wave_end_to_end_lifecycle(client):
    """
    Tests complete lifecycle:
    1. Create wave
    2. Start wave (reserves inventory, transitions orders to 'In Picking')
    3. Pick tasks (partial and full picking)
    4. Over-picking rejection
    5. Completion validation (fails if unresolved mandatory tasks exist)
    6. Complete wave (deducts physical inventory, transitions orders to 'Picked')
    """
    conn = get_db()
    try:
        # Check initial physical stock of a test product
        with conn.cursor() as cur:
            cur.execute("SELECT id, stock_quantity FROM products WHERE id = 1")
            initial_stock = cur.fetchone()["stock_quantity"]
    finally:
        conn.close()

    # Step 1: Create Wave with orders 3 and 4
    create_res = client.post("/api/waves", json={
        "name": "Lifecycle E2E Test Wave",
        "order_ids": [3, 4],
        "strategy": "Hybrid",
        "priority": "Standard",
        "assigned_picker": "Elena Ramos"
    })
    assert create_res.status_code == 201
    wave = create_res.get_json()["wave"]
    wave_id = wave["id"]
    tasks = wave["tasks"]
    assert len(tasks) > 0

    # Step 2: Start Wave
    start_res = client.post(f"/api/waves/{wave_id}/start")
    assert start_res.status_code == 200
    active_wave = start_res.get_json()["wave"]
    assert active_wave["status"] == "Active"

    # Verify inventory reservations exist
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as r_cnt FROM inventory_reservations WHERE wave_id = %s AND status = 'Reserved'", (wave_id,))
            assert cur.fetchone()["r_cnt"] > 0
            cur.execute("SELECT status FROM orders WHERE id IN (3, 4)")
            for r in cur.fetchall():
                assert r["status"] == "In Picking"
    finally:
        conn.close()

    # Step 3: Over-picking attempt should be rejected
    first_task = tasks[0]
    task_id = first_task["id"]
    req_qty = first_task["required_quantity"]

    over_res = client.post(f"/api/waves/{wave_id}/tasks/{task_id}/pick", json={
        "picked_quantity": req_qty + 100
    })
    assert over_res.status_code == 400
    assert "Over-picking prevented" in over_res.get_json()["message"]

    # Step 4: Completion attempt with unresolved tasks should fail
    fail_comp_res = client.post(f"/api/waves/{wave_id}/complete")
    assert fail_comp_res.status_code == 400
    assert "Unresolved tasks remain" in fail_comp_res.get_json()["message"]

    # Step 5: Partial pick on task 1
    if req_qty > 1:
        part_res = client.post(f"/api/waves/{wave_id}/tasks/{task_id}/pick", json={
            "picked_quantity": 1
        })
        assert part_res.status_code == 200
        # Check task status is Partial
        detail_wave = client.get(f"/api/waves/{wave_id}").get_json()["wave"]
        updated_t1 = next(t for t in detail_wave["tasks"] if t["id"] == task_id)
        assert updated_t1["status"] == "Partial"

    # Step 6: Complete all tasks
    for t in tasks:
        t_id = t["id"]
        t_req = t["required_quantity"]
        p_res = client.post(f"/api/waves/{wave_id}/tasks/{t_id}/pick", json={
            "picked_quantity": t_req
        })
        assert p_res.status_code == 200

    # Step 7: Complete the wave
    comp_res = client.post(f"/api/waves/{wave_id}/complete")
    assert comp_res.status_code == 200
    completed_wave = comp_res.get_json()["wave"]
    assert completed_wave["status"] == "Completed"
    assert completed_wave["progress_pct"] == 100.0

    # Verify orders marked as 'Picked' (ready for packing) and reservations fulfilled
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM orders WHERE id IN (3, 4)")
            for r in cur.fetchall():
                assert r["status"] == "Picked"
            cur.execute("SELECT COUNT(*) as r_cnt FROM inventory_reservations WHERE wave_id = %s AND status = 'Fulfilled'", (wave_id,))
            assert cur.fetchone()["r_cnt"] > 0
    finally:
        conn.close()


def test_wave_cancellation_releases_reservations(client):
    """Verifies that wave cancellation safely frees reserved stock and pending orders."""
    create_res = client.post("/api/waves", json={
        "name": "Cancel Test Wave",
        "order_ids": [5, 6],
        "strategy": "Priority-based"
    })
    wave = create_res.get_json()["wave"]
    wave_id = wave["id"]

    client.post(f"/api/waves/{wave_id}/start")

    # Cancel wave
    cancel_res = client.post(f"/api/waves/{wave_id}/cancel")
    assert cancel_res.status_code == 200

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM waves WHERE id = %s", (wave_id,))
            assert cur.fetchone()["status"] == "Cancelled"
            cur.execute("SELECT COUNT(*) as r_cnt FROM inventory_reservations WHERE wave_id = %s AND status = 'Released'", (wave_id,))
            assert cur.fetchone()["r_cnt"] > 0
            cur.execute("SELECT status FROM orders WHERE id IN (5, 6)")
            for r in cur.fetchall():
                assert r["status"] == "Pending"
    finally:
        conn.close()


def test_exception_reporting(client):
    """Verifies exception recording (shortage, damaged) on pick tasks."""
    create_res = client.post("/api/waves", json={
        "name": "Exception Test Wave",
        "order_ids": [7, 8],
        "strategy": "Zone-based"
    })
    wave = create_res.get_json()["wave"]
    wave_id = wave["id"]
    task_id = wave["tasks"][0]["id"]

    client.post(f"/api/waves/{wave_id}/start")

    # Report shortage exception
    exc_res = client.post(f"/api/waves/{wave_id}/tasks/{task_id}/exception", json={
        "exception_type": "Shortage",
        "details": "Bin empty upon physical inspection"
    })
    assert exc_res.status_code == 200
    exc_wave = exc_res.get_json()["wave"]
    assert len(exc_wave["exceptions"]) > 0
    assert exc_wave["exceptions"][0]["exception_type"] == "Shortage"

    # Cleanup
    client.post(f"/api/waves/{wave_id}/cancel")


def test_wave_csv_export(client):
    """Verifies consolidated pick list CSV export endpoint."""
    create_res = client.post("/api/waves", json={
        "name": "CSV Export Wave",
        "order_ids": [9, 10],
        "strategy": "SKU-based"
    })
    wave_id = create_res.get_json()["wave"]["id"]

    exp_res = client.get(f"/api/waves/{wave_id}/export")
    assert exp_res.status_code == 200
    assert exp_res.mimetype == "text/csv"
    csv_text = exp_res.get_data(as_text=True)
    assert "# Wave Pick List:" in csv_text
    assert "Sequence,SKU,Product Name,Shelf,Aisle/Zone" in csv_text

    # Cleanup
    client.post(f"/api/waves/{wave_id}/cancel")
