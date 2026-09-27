"""
tests/test_fleet_allocator.py
Automated tests for Multi-Worker Fleet Balancing (backend/fleet_allocator.py)
"""

import pytest
from backend.warehouse import Warehouse
from backend.models import Order
from backend.fleet_allocator import FleetAllocator


def test_fleet_balancing_makespan_and_gini():
    w = Warehouse()
    for i in range(1, 10):
        w.add_edge(i, i + 1, 10.0)
    w.add_edge(10, 1, 10.0)

    orders = [
        Order(1, "Cust A", items=[{"product_id": 1, "quantity": 2, "shelf_id": 2}]),
        Order(2, "Cust B", items=[{"product_id": 2, "quantity": 1, "shelf_id": 4}]),
        Order(3, "Cust C", items=[{"product_id": 3, "quantity": 3, "shelf_id": 6}]),
        Order(4, "Cust D", items=[{"product_id": 4, "quantity": 2, "shelf_id": 8}])
    ]

    allocator = FleetAllocator(w, ["Worker 1", "Worker 2"])
    plans, metrics = allocator.allocate(orders)

    assert metrics["fleet_size"] == 2
    assert len(plans) == 2
    assert metrics["makespan_distance"] > 0
    # Gini coefficient must be low for a balanced shift
    assert metrics["gini_coefficient"] <= 0.25
    assert metrics["is_balanced"] is True
