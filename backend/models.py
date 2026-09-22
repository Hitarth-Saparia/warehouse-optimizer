"""
backend/models.py
Core Object-Oriented Domain Entities matching the database tables:
- Product
- Shelf
- Order
- Worker
"""

class Product:
    def __init__(self, id, name, category, assigned_shelf_id=None, pick_frequency=0):
        self.id = id
        self.name = name
        self.category = category
        self.assigned_shelf_id = assigned_shelf_id
        self.pick_frequency = pick_frequency

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "assigned_shelf_id": self.assigned_shelf_id,
            "pick_frequency": self.pick_frequency
        }

class Shelf:
    def __init__(self, id, distance_to_packing, capacity=5, current_load=0, x=0, y=0):
        self.id = id
        self.distance_to_packing = float(distance_to_packing)
        self.capacity = capacity
        self.current_load = current_load
        self.x = x
        self.y = y

    def is_full(self):
        return self.current_load >= self.capacity

    def to_dict(self):
        return {
            "id": self.id,
            "distance_to_packing": self.distance_to_packing,
            "capacity": self.capacity,
            "current_load": self.current_load,
            "x": self.x,
            "y": self.y
        }

class Order:
    def __init__(self, id, customer_name, status="Pending", items=None):
        self.id = id
        self.customer_name = customer_name
        self.status = status
        self.items = items or [] # list of dicts: {"product_id": ..., "name": ..., "quantity": ..., "shelf_id": ...}

    def to_dict(self):
        return {
            "id": self.id,
            "customer_name": self.customer_name,
            "status": self.status,
            "item_count": len(self.items),
            "items": self.items
        }

class Worker:
    def __init__(self, id, name, current_shelf_id=1):
        self.id = id
        self.name = name
        self.current_shelf_id = current_shelf_id

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "current_shelf_id": self.current_shelf_id
        }
