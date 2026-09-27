"""
tests/test_batch_optimizer.py
Automated tests for Wave Picking & Order Batching Problem (backend/batch_optimizer.py)
"""

import pytest
from backend.warehouse import Warehouse
from backend.models import Order
from backend.batch_optimizer import BatchOptimizer


def test_wave_batching_capacity_and_savings():
    w = Warehouse()
    for i in range(1, 8):
        w.add_edge(i, i + 1, 10.0)
    w.add_edge(8, 1, 10.0)

    # 3 companion orders
    orders = [
        Order(1, "Cust A", items=[{"product_id": 1, "quantity": 2, "shelf_id": 2}]),
        Order(2, "Cust B", items=[{"product_id": 2, "quantity": 3, "shelf_id": 3}]),
        Order(3, "Cust C", items=[{"product_id": 3, "quantity": 2, "shelf_id": 4}])
    ]

    # Cart capacity of 10 can fit all 7 units into 1 single wave
    bo = BatchOptimizer(w, max_cart_capacity=10)
    batches, metrics = bo.optimize_batches(orders)

    assert metrics["total_batches"] == 1
    assert metrics["percent_reduction"] > 0
    assert metrics["distance_saved"] > 0
    assert len(batches[0]["order_ids"]) == 3
