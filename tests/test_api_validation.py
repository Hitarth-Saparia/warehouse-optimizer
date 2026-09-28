"""
tests/test_api_validation.py
Automated tests for API Input Validation and Defensive Error Handling.
Ensures invalid inputs (bad types, empty payloads, invalid IDs) return 400 Bad Request
instead of unhandled 500 exceptions.
"""

import pytest
from backend.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_corridor_block_validation(client):
    # Missing parameters
    resp = client.post("/api/warehouse/corridor/block", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    # Non-integer shelf IDs
    resp = client.post("/api/warehouse/corridor/block", json={"from_shelf": "invalid", "to_shelf": 2})
    assert resp.status_code == 400
    assert "integers" in resp.get_json()["error"]

    # Non-numeric penalty
    resp = client.post("/api/warehouse/corridor/block", json={"from_shelf": 2, "to_shelf": 3, "penalty": "bad_num"})
    assert resp.status_code == 400
    assert "valid number" in resp.get_json()["error"]


def test_order_status_validation(client):
    # Invalid lifecycle status
    resp = client.patch("/api/orders/1/status", json={"status": "Exploded"})
    assert resp.status_code == 400
    assert "Invalid status" in resp.get_json()["error"]

    # Empty payload
    resp = client.patch("/api/orders/1/status", json={})
    assert resp.status_code == 400


def test_inventory_restock_validation(client):
    # Empty payload
    resp = client.post("/api/inventory/restock", json={})
    assert resp.status_code == 400

    # Non-integer product_id
    resp = client.post("/api/inventory/restock", json={"product_id": "abc", "quantity": 10})
    assert resp.status_code == 400
    assert "valid integers" in resp.get_json()["error"]

    # Negative quantity
    resp = client.post("/api/inventory/restock", json={"product_id": 1, "quantity": -5})
    assert resp.status_code == 400
    assert "greater than 0" in resp.get_json()["error"]

    # Invalid restock_all_to
    resp = client.post("/api/inventory/restock", json={"restock_all_to": "not_a_number"})
    assert resp.status_code == 400


def test_order_creation_validation(client):
    # Missing customer name
    resp = client.post("/api/orders/create", json={"items": [{"product_id": 1, "quantity": 2}]})
    assert resp.status_code == 400
    assert "customer_name is required" in resp.get_json()["error"]

    # Empty items list
    resp = client.post("/api/orders/create", json={"customer_name": "Test Co", "items": []})
    assert resp.status_code == 400
    assert "items list is required" in resp.get_json()["error"]

    # Invalid item format
    resp = client.post("/api/orders/create", json={"customer_name": "Test Co", "items": ["invalid"]})
    assert resp.status_code == 400


def test_query_param_defensive_fallbacks(client):
    # Invalid cart_capacity string falls back to default safely without 500 error
    resp = client.get("/api/batch/waves?cart_capacity=invalid_string")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cart_capacity"] == 35  # default

    # Invalid workers parameter falls back safely
    resp = client.get("/api/fleet/assign?workers=not_a_number")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["workers"]) == 3  # default
