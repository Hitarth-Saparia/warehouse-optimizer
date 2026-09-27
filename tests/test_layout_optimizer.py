"""
tests/test_layout_optimizer.py
Automated tests for Operations Research & Greedy Slotting (backend/layout_optimizer.py)
"""

import pytest
from backend.models import Product, Shelf
from backend.layout_optimizer import LayoutOptimizer


def test_greedy_slotting_velocity_priority():
    shelves = [
        Shelf(id=1, distance_to_packing=0.0),
        Shelf(id=2, distance_to_packing=10.0),
        Shelf(id=3, distance_to_packing=25.0)
    ]

    products = [
        Product(id=1, name="Fast Item", category="Electronics", assigned_shelf_id=3, pick_frequency=500),
        Product(id=2, name="Slow Item", category="Electronics", assigned_shelf_id=2, pick_frequency=10)
    ]

    opt = LayoutOptimizer()
    assignments, summary = opt.optimize(products, shelves)

    fast_assignment = next(a for a in assignments if a["product_id"] == 1)
    # High-velocity product must be moved to Shelf 2 (closest storage shelf)
    assert fast_assignment["new_shelf_id"] == 2
    assert summary["moved_count"] >= 1
    assert summary["weighted_demand_reduction_pct"] > 0


def test_capacity_and_safety_constraints():
    # Shelf 2 has capacity 2, Shelf 3 has capacity 5
    shelves = [
        Shelf(id=1, distance_to_packing=0.0),
        Shelf(id=2, distance_to_packing=10.0, capacity=2),
        Shelf(id=3, distance_to_packing=30.0, capacity=5)
    ]

    products = [
        Product(id=1, name="Fragile Item A", category="Fragile", assigned_shelf_id=3, pick_frequency=300),
        Product(id=2, name="Heavy Item B", category="Heavy", assigned_shelf_id=3, pick_frequency=250),
        Product(id=3, name="Fragile Item C", category="Fragile", assigned_shelf_id=3, pick_frequency=200)
    ]

    opt = LayoutOptimizer()
    assignments, summary = opt.optimize(products, shelves)

    # Check Fragile and Heavy are NEVER on the same shelf
    shelf_items = {}
    for a in assignments:
        s_id = a["new_shelf_id"]
        shelf_items.setdefault(s_id, []).append(a["category"])

    for s_id, categories in shelf_items.items():
        assert not ("Fragile" in categories and "Heavy" in categories), f"Safety violation on Shelf {s_id}!"
        # Check capacity
        assert len(categories) <= 5
