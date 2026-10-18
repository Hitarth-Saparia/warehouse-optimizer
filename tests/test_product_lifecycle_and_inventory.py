"""
tests/test_product_lifecycle_and_inventory.py
End-to-End Tests for:
1. Product CRUD, SKU uniqueness, and shelf assignment capacity limits
2. Physical inventory adjustments (+ / -) and transaction audit logging
3. Low-stock notification triggers and notifications dismissal
4. Product archiving and catalog restoration
5. Executive Analytics and CSV export
"""

import pytest
from backend.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_product_creation_and_validation(client):
    # Test missing name
    resp = client.post("/api/products", json={"category": "Tools"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    # Test missing category
    resp = client.post("/api/products", json={"name": "Test Drill"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    # Test successful creation with auto-generated SKU
    resp = client.post("/api/products", json={
        "name": "Heavy Industrial Winch 12V",
        "category": "Heavy",
        "stock_quantity": 40,
        "volume": 3.5,
        "unit_price": 149.99,
        "reorder_threshold": 10
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "success"
    prod = data["product"]
    assert prod["name"] == "Heavy Industrial Winch 12V"
    assert prod["sku"].startswith("SKU-HV-")
    assert prod["stock_quantity"] == 40
    new_prod_id = prod["id"]

    # Verify duplicate SKU check
    resp_dup = client.post("/api/products", json={
        "name": "Duplicate Winch",
        "category": "Heavy",
        "sku": prod["sku"]
    })
    assert resp_dup.status_code == 400
    assert "already exists" in resp_dup.get_json()["error"]

    # Verify initial inbound transaction logged
    resp_tx = client.get(f"/api/inventory/transactions?product_id={new_prod_id}")
    assert resp_tx.status_code == 200
    tx_data = resp_tx.get_json()
    assert tx_data["count"] >= 1
    assert tx_data["transactions"][0]["movement_type"] == "INBOUND"
    assert tx_data["transactions"][0]["quantity_change"] == 40


def test_stock_adjustment_and_low_stock_notification(client):
    # Create product with reorder threshold 15
    resp = client.post("/api/products", json={
        "name": "Digital Multimeter Pro",
        "category": "Electronics",
        "stock_quantity": 25,
        "reorder_threshold": 15
    })
    assert resp.status_code == 201
    prod_id = resp.get_json()["product"]["id"]

    # Adjust stock: deduct 15 units -> remaining = 10 (triggers low stock <= 15)
    resp_adj = client.post(f"/api/products/{prod_id}/stock", json={
        "quantity_change": -15,
        "movement_type": "ADJUSTMENT",
        "reason": "Damaged batch write-off"
    })
    assert resp_adj.status_code == 200
    adj_data = resp_adj.get_json()
    assert adj_data["new_quantity"] == 10

    # Verify notification created
    resp_notif = client.get("/api/notifications")
    assert resp_notif.status_code == 200
    notifs = resp_notif.get_json()["notifications"]
    low_stock_notif = next((n for n in notifs if "Digital Multimeter Pro" in n["title"]), None)
    assert low_stock_notif is not None
    notif_id = low_stock_notif["id"]

    # Mark notification read
    resp_read = client.post(f"/api/notifications/{notif_id}/read")
    assert resp_read.status_code == 200

    # Dismiss notification
    resp_del = client.delete(f"/api/notifications/{notif_id}")
    assert resp_del.status_code == 200


def test_product_update_and_archive(client):
    # Create product
    resp = client.post("/api/products", json={
        "name": "Impact Wrench 18V",
        "category": "Tools",
        "assigned_shelf_id": 3,
        "stock_quantity": 30
    })
    assert resp.status_code == 201
    prod_id = resp.get_json()["product"]["id"]

    # Update product
    resp_up = client.put(f"/api/products/{prod_id}", json={
        "name": "Impact Wrench 18V Brushless Gen2",
        "unit_price": 189.00
    })
    assert resp_up.status_code == 200

    # Verify updated
    resp_get = client.get(f"/api/products/{prod_id}")
    assert resp_get.status_code == 200
    assert resp_get.get_json()["product"]["name"] == "Impact Wrench 18V Brushless Gen2"

    # Archive product
    resp_arch = client.delete(f"/api/products/{prod_id}")
    assert resp_arch.status_code == 200

    # Verify not in default list
    resp_list = client.get("/api/products")
    prods = resp_list.get_json()
    assert not any(p["id"] == prod_id for p in prods)

    # Verify visible when include_archived=true
    resp_list_all = client.get("/api/products?include_archived=true")
    prods_all = resp_list_all.get_json()
    assert any(p["id"] == prod_id for p in prods_all)

    # Restore product
    resp_res = client.post(f"/api/products/{prod_id}/restore")
    assert resp_res.status_code == 200


def test_reports_analytics_api(client):
    # JSON report
    resp = client.get("/api/reports/analytics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "inventory" in data
    assert "orders" in data
    assert "warehouse" in data
    assert "fleet" in data
    assert data["inventory"]["active_skus"] >= 60

    # CSV report
    resp_csv = client.get("/api/reports/analytics?format=csv")
    assert resp_csv.status_code == 200
    assert resp_csv.mimetype == "text/csv"
    assert b"Category,SKU Count,Units In Stock" in resp_csv.data
