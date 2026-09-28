"""
tests/test_inventory_management.py
Automated tests for Inventory Stock Management & Product Stock Levels
"""

from backend.models import Product

def test_product_stock_levels():
    p = Product(id=1, name="Electric Screwdriver", category="Tools", assigned_shelf_id=3, pick_frequency=120, stock_quantity=45)
    assert p.stock_quantity == 45
    d = p.to_dict()
    assert d["stock_quantity"] == 45

    # Default stock level
    p2 = Product(id=2, name="Bolt M8", category="Fasteners", assigned_shelf_id=4)
    assert p2.stock_quantity == 50
    assert p2.to_dict()["stock_quantity"] == 50
