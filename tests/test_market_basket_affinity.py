"""
tests/test_market_basket_affinity.py
Automated tests for Market Basket Analysis, Product Co-Affinity Mining, and Bundle Slotting.
"""

import pytest
from backend.models import Product, Shelf
from backend.layout_optimizer import (
    LayoutOptimizer,
    mine_market_basket_affinity,
    build_affinity_bundles
)
from backend.app import app


def test_mine_market_basket_affinity_metrics():
    """Validates calculation of Support, Confidence, and Lift for co-ordered products."""
    products = [
        Product(id=1, name="Screwdriver Set", category="Tools", assigned_shelf_id=2, pick_frequency=50),
        Product(id=2, name="Wall Anchors Box", category="Fasteners", assigned_shelf_id=3, pick_frequency=45),
        Product(id=3, name="Cordless Drill", category="Tools", assigned_shelf_id=4, pick_frequency=20),
    ]

    # 4 orders:
    # Order 1: [1, 2]
    # Order 2: [1, 2, 3]
    # Order 3: [1, 3]
    # Order 4: [2]
    order_baskets = [
        [1, 2],
        [1, 2, 3],
        [1, 3],
        [2]
    ]

    pairs = mine_market_basket_affinity(order_baskets, products)
    assert len(pairs) > 0

    # Check pair (1, 2): appears in 2 of 4 orders
    pair_1_2 = next((p for p in pairs if (p["product_id_1"] == 1 and p["product_id_2"] == 2)), None)
    assert pair_1_2 is not None
    assert pair_1_2["co_occurrence_count"] == 2
    assert pair_1_2["support"] == 0.5  # 2 / 4
    # Item 1 appears in 3 orders (1, 2, 3) -> conf = 2/3 = 0.667
    assert pair_1_2["confidence"] >= 0.66


def test_affinity_bundles_safety_segregation():
    """Ensures Fragile and Heavy items are never bundled together even with high affinity."""
    products = [
        Product(id=10, name="Glass Beaker", category="Fragile", assigned_shelf_id=2, pick_frequency=80),
        Product(id=11, name="Anvil Sledge", category="Heavy", assigned_shelf_id=3, pick_frequency=90),
        Product(id=12, name="Safety Tape", category="Safety", assigned_shelf_id=4, pick_frequency=40),
    ]

    # Simulated top pairs claiming item 10 and 11 co-occur frequently
    top_pairs = [
        {
            "product_id_1": 10,
            "product_name_1": "Glass Beaker",
            "category_1": "Fragile",
            "sku_1": "SKU-0010",
            "product_id_2": 11,
            "product_name_2": "Anvil Sledge",
            "category_2": "Heavy",
            "sku_2": "SKU-0011",
            "co_occurrence_count": 5,
            "support": 0.5,
            "confidence": 0.8,
            "lift": 2.5
        },
        {
            "product_id_1": 10,
            "product_name_1": "Glass Beaker",
            "category_1": "Fragile",
            "sku_1": "SKU-0010",
            "product_id_2": 12,
            "product_name_2": "Safety Tape",
            "category_2": "Safety",
            "sku_2": "SKU-0012",
            "co_occurrence_count": 3,
            "support": 0.3,
            "confidence": 0.6,
            "lift": 1.5
        }
    ]

    bundles = build_affinity_bundles(top_pairs, products)

    # Verify no bundle contains both Fragile and Heavy
    for b in bundles:
        categories = {p.category for p in b}
        assert not ("Fragile" in categories and "Heavy" in categories), "Safety violation in bundle!"


def test_layout_optimizer_affinity_strategy():
    """Validates full execution of layout optimizer in affinity strategy mode."""
    shelves = [
        Shelf(id=1, distance_to_packing=0.0),
        Shelf(id=2, distance_to_packing=10.0, capacity=3),
        Shelf(id=3, distance_to_packing=25.0, capacity=3),
        Shelf(id=4, distance_to_packing=40.0, capacity=3)
    ]

    products = [
        Product(id=1, name="Item A", category="Electronics", assigned_shelf_id=4, pick_frequency=120),
        Product(id=2, name="Item B", category="Electronics", assigned_shelf_id=4, pick_frequency=110),
        Product(id=3, name="Item C", category="Tools", assigned_shelf_id=3, pick_frequency=50),
        Product(id=4, name="Item D", category="Tools", assigned_shelf_id=3, pick_frequency=40)
    ]

    order_baskets = [
        [1, 2],
        [1, 2],
        [3, 4]
    ]

    opt = LayoutOptimizer()
    assignments, summary = opt.optimize(products, shelves, strategy="affinity", order_baskets=order_baskets)

    assert summary["strategy"] == "affinity"
    assert "affinity_metrics" in summary
    assert summary["affinity_metrics"]["total_pairs_mined"] >= 1
    assert len(assignments) == 4

    # High affinity pair [1, 2] with high velocity should land together on the closest storage shelf (Shelf 2)
    s1 = next(a["new_shelf_id"] for a in assignments if a["product_id"] == 1)
    s2 = next(a["new_shelf_id"] for a in assignments if a["product_id"] == 2)
    assert s1 == s2 == 2, f"Expected items 1 & 2 co-located on Shelf 2, got {s1} & {s2}"


def test_api_market_basket_affinity():
    """Validates REST API endpoint /api/market-basket/affinity returns 200 OK and valid JSON."""
    client = app.test_client()
    res = client.get("/api/market-basket/affinity")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "top_pairs" in data
    assert "total_pairs_mined" in data


def test_api_layout_optimize_affinity_strategy():
    """Validates REST API endpoint /api/layout/optimize?strategy=affinity returns 200 OK."""
    client = app.test_client()
    res = client.get("/api/layout/optimize?strategy=affinity")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["strategy"] == "affinity"
    assert "affinity_metrics" in data["summary"]
