"""
backend/models.py
Core Object-Oriented Domain Entities matching the database tables:
- Product
- Shelf
- Order
- Worker
- User (RBAC & Authentication Domain Model)
- AuditLog (Security Audit Trail)
"""

class Product:
    def __init__(self, id, name, category, assigned_shelf_id=None, pick_frequency=0, stock_quantity=50):
        self.id = id
        self.name = name
        self.category = category
        self.assigned_shelf_id = assigned_shelf_id
        self.pick_frequency = float(pick_frequency or 0)
        self.stock_quantity = int(stock_quantity if stock_quantity is not None else 50)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "assigned_shelf_id": self.assigned_shelf_id,
            "pick_frequency": self.pick_frequency,
            "stock_quantity": self.stock_quantity
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

    @property
    def item_count(self):
        return len(self.items)

    def to_dict(self):
        return {
            "id": self.id,
            "customer_name": self.customer_name,
            "status": self.status,
            "item_count": self.item_count,
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


class User:
    """
    User domain entity representing an authenticated warehouse operator.
    Implements Role-Based Access Control (RBAC) domain rules:
    - manager: full administrative control (layout re-slotting, fleet allocation, route picking, audits)
    - supervisor: picking supervisor (picking execution, corridor blockages)
    - fleet: fleet coordinator (mTSP fleet balancing and wave batch allocations)
    - guest: read-only analytics and metrics exploration
    """

    ROLE_PERMISSIONS = {
        "manager": {
            "can_modify_layout": True,
            "can_manage_fleet": True,
            "can_pick_orders": True,
            "can_view_audit": True,
            "can_manage_corridors": True
        },
        "supervisor": {
            "can_modify_layout": False,
            "can_manage_fleet": False,
            "can_pick_orders": True,
            "can_view_audit": False,
            "can_manage_corridors": True
        },
        "fleet": {
            "can_modify_layout": False,
            "can_manage_fleet": True,
            "can_pick_orders": True,
            "can_view_audit": False,
            "can_manage_corridors": False
        },
        "guest": {
            "can_modify_layout": False,
            "can_manage_fleet": False,
            "can_pick_orders": False,
            "can_view_audit": False,
            "can_manage_corridors": False
        }
    }

    def __init__(self, id, email, name, password_hash, salt, role="guest", created_at=None, last_login=None):
        self.id = id
        self.email = email
        self.name = name
        self.password_hash = password_hash
        self.salt = salt
        self.role = role.lower() if role else "guest"
        self.created_at = created_at
        self.last_login = last_login

    def verify_password(self, plain_password: str) -> bool:
        """Verifies candidate plaintext password against stored cryptographic salt & hash."""
        from backend.security import verify_password
        return verify_password(plain_password, self.password_hash, self.salt)

    def has_permission(self, permission: str) -> bool:
        """Evaluates whether the user's role grants the requested operational permission."""
        role_matrix = self.ROLE_PERMISSIONS.get(self.role, self.ROLE_PERMISSIONS["guest"])
        return role_matrix.get(permission, False)

    @property
    def permissions(self) -> dict:
        """Returns the full capability dictionary for this user's role."""
        return self.ROLE_PERMISSIONS.get(self.role, self.ROLE_PERMISSIONS["guest"]).copy()

    @property
    def initials(self) -> str:
        """Generates 2-letter uppercase avatar initials from the user's name."""
        parts = self.name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        elif parts:
            return parts[0][:2].upper()
        return "U"

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Serializes domain model to a secure, JSON-serializable dictionary."""
        data = {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "initials": self.initials,
            "permissions": self.permissions,
            "created_at": str(self.created_at) if self.created_at else None,
            "last_login": str(self.last_login) if self.last_login else None
        }
        if include_sensitive:
            data["password_hash"] = self.password_hash
            data["salt"] = self.salt
        return data


class AuditLog:
    """
    AuditLog domain entity representing a security or authentication audit event.
    """
    def __init__(self, id, user_id, email, action, ip_address, status, details=None, created_at=None):
        self.id = id
        self.user_id = user_id
        self.email = email
        self.action = action
        self.ip_address = ip_address
        self.status = status
        self.details = details
        self.created_at = created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "email": self.email,
            "action": self.action,
            "ip_address": self.ip_address,
            "status": self.status,
            "details": self.details,
            "created_at": str(self.created_at) if self.created_at else None
        }
