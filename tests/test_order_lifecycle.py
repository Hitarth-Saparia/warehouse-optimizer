"""
tests/test_order_lifecycle.py
Automated tests for Order Lifecycle & Status Management (CRUD)
"""

from backend.models import Order

def test_order_model_lifecycle():
    order = Order(id=101, customer_name="Test Logistics", status="Pending", items=[
        {"product_id": 1, "name": "Item A", "quantity": 3, "shelf_id": 2}
    ])
    
    assert order.status == "Pending"
    assert order.item_count == 1
    d = order.to_dict()
    assert d["status"] == "Pending"
    assert d["item_count"] == 1
    
    # Transition to Picking
    order.status = "Picking"
    assert order.to_dict()["status"] == "Picking"
    
    # Transition to Completed
    order.status = "Completed"
    assert order.to_dict()["status"] == "Completed"
