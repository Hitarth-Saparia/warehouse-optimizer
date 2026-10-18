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
    def __init__(self, id, name, category, assigned_shelf_id=None, pick_frequency=0, stock_quantity=50, volume=1.0):
        self.id = id
        self.name = name
        self.category = category
        self.assigned_shelf_id = assigned_shelf_id
        self.pick_frequency = float(pick_frequency or 0)
        self.stock_quantity = int(stock_quantity if stock_quantity is not None else 50)
        self.volume = float(volume if volume is not None else 1.0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "assigned_shelf_id": self.assigned_shelf_id,
            "pick_frequency": self.pick_frequency,
            "stock_quantity": self.stock_quantity,
            "volume": self.volume
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
    def __init__(self, id, customer_name, status="Pending", items=None,
                 weight=None, destination_zone="Zone A - Downtown", priority="Standard",
                 deadline="18:00", warehouse_id="WH-01", assigned_vehicle_id=None):
        self.id = id
        self.customer_name = customer_name
        self.status = status
        self.items = items or [] # list of dicts: {"product_id": ..., "name": ..., "quantity": ..., "shelf_id": ...}

        # Calculate dynamic weight if not explicitly provided
        if weight is not None and float(weight) > 0:
            self.weight = round(float(weight), 1)
        else:
            total_qty = sum(it.get("quantity", 1) for it in self.items)
            self.weight = round(max(12.0, total_qty * 8.5), 1)

        self.destination_zone = destination_zone or "Zone A - Downtown"
        self.priority = priority or "Standard"
        self.deadline = deadline or "18:00"
        self.warehouse_id = warehouse_id or "WH-01"
        self.assigned_vehicle_id = str(assigned_vehicle_id) if assigned_vehicle_id else None

    @property
    def item_count(self):
        return len(self.items)

    @property
    def total_units(self):
        return sum(it.get("quantity", 1) for it in self.items)

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.id,
            "customer_name": self.customer_name,
            "status": self.status,
            "item_count": self.item_count,
            "total_units": self.total_units,
            "weight": self.weight,
            "destination_zone": self.destination_zone,
            "priority": self.priority,
            "deadline": self.deadline,
            "warehouse_id": self.warehouse_id,
            "assigned_vehicle_id": self.assigned_vehicle_id,
            "items": self.items
        }

class Vehicle:
    """
    Vehicle domain entity representing a fleet delivery vehicle.
    Tracks capacity, load, station location, availability status, and cost profile.
    """
    def __init__(self, id, name, vehicle_type, max_capacity, current_load=0.0,
                 location="WH-01", status="Available", cost_per_km=1.85, fixed_cost=25.0,
                 created_at=None):
        self.id = str(id).strip()
        self.name = str(name).strip()
        self.vehicle_type = str(vehicle_type).strip()
        self.max_capacity = float(max_capacity)
        self.current_load = float(current_load or 0.0)
        self.location = str(location).strip()
        self.status = str(status).strip() # "Available", "In Transit", "Maintenance"
        self.cost_per_km = float(cost_per_km if cost_per_km is not None else 1.85)
        self.fixed_cost = float(fixed_cost if fixed_cost is not None else 25.0)
        self.created_at = created_at

    @property
    def available_capacity(self):
        return max(0.0, round(self.max_capacity - self.current_load, 1))

    @property
    def utilization_pct(self):
        if self.max_capacity <= 0:
            return 0.0
        return round((self.current_load / self.max_capacity) * 100.0, 1)

    @property
    def is_available(self):
        return self.status.lower() == "available"

    @property
    def is_overloaded(self):
        return self.current_load > self.max_capacity

    @property
    def is_underutilized(self):
        return self.is_available and 0.0 < self.utilization_pct < 50.0

    @property
    def is_idle(self):
        return self.is_available and self.current_load <= 0.0

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "vehicle_type": self.vehicle_type,
            "max_capacity": self.max_capacity,
            "current_load": round(self.current_load, 1),
            "available_capacity": self.available_capacity,
            "utilization_pct": self.utilization_pct,
            "location": self.location,
            "status": self.status,
            "cost_per_km": self.cost_per_km,
            "fixed_cost": self.fixed_cost,
            "is_available": self.is_available,
            "is_overloaded": self.is_overloaded,
            "is_underutilized": self.is_underutilized,
            "is_idle": self.is_idle,
            "created_at": str(self.created_at) if self.created_at else None
        }

class WarehouseLocation:
    """
    Warehouse/Logistics Hub domain entity representing regional distribution centers.
    """
    def __init__(self, id, name, location, coord_x=0.0, coord_y=0.0, service_zones=None):
        self.id = str(id).strip()
        self.name = str(name).strip()
        self.location = str(location).strip()
        self.coord_x = float(coord_x or 0.0)
        self.coord_y = float(coord_y or 0.0)
        self.service_zones = service_zones or ["Zone A - Downtown", "Zone B - East Industrial"]

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "coord_x": self.coord_x,
            "coord_y": self.coord_y,
            "service_zones": self.service_zones
        }

class BalancingRun:
    """
    Domain entity tracking execution history of Fleet Balancing runs.
    """
    def __init__(self, id, status="Proposed", total_vehicles=0, assigned_orders_count=0,
                 unassigned_orders_count=0, fleet_utilization_pct=0.0, cost_before=0.0,
                 cost_after=0.0, cost_savings=0.0, distance_before=0.0, distance_after=0.0,
                 summary_json=None, created_at=None):
        self.id = id
        self.status = status # "Proposed", "Applied", "Discarded"
        self.total_vehicles = int(total_vehicles or 0)
        self.assigned_orders_count = int(assigned_orders_count or 0)
        self.unassigned_orders_count = int(unassigned_orders_count or 0)
        self.fleet_utilization_pct = float(fleet_utilization_pct or 0.0)
        self.cost_before = float(cost_before or 0.0)
        self.cost_after = float(cost_after or 0.0)
        self.cost_savings = float(cost_savings or 0.0)
        self.distance_before = float(distance_before or 0.0)
        self.distance_after = float(distance_after or 0.0)
        self.summary_json = summary_json
        self.created_at = created_at

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "total_vehicles": self.total_vehicles,
            "assigned_orders_count": self.assigned_orders_count,
            "unassigned_orders_count": self.unassigned_orders_count,
            "fleet_utilization_pct": self.fleet_utilization_pct,
            "cost_before": self.cost_before,
            "cost_after": self.cost_after,
            "cost_savings": self.cost_savings,
            "distance_before": self.distance_before,
            "distance_after": self.distance_after,
            "created_at": str(self.created_at) if self.created_at else None
        }

class VehicleAssignment:
    """
    Domain entity recording vehicle to order assignment relationship.
    """
    def __init__(self, id, vehicle_id, order_id, run_id=None, assigned_at=None, status="Assigned"):
        self.id = id
        self.vehicle_id = str(vehicle_id)
        self.order_id = int(order_id)
        self.run_id = run_id
        self.assigned_at = assigned_at
        self.status = status

    def to_dict(self):
        return {
            "id": self.id,
            "vehicle_id": self.vehicle_id,
            "order_id": self.order_id,
            "run_id": self.run_id,
            "assigned_at": str(self.assigned_at) if self.assigned_at else None,
            "status": self.status
        }

class Wave:
    """
    Wave Picking domain entity representing a consolidated picking batch of orders.
    Tracks lifecycle: Draft -> Scheduled -> Active -> (Paused) -> Completed / Cancelled.
    """
    def __init__(self, id, name, status="Draft", strategy="Hybrid", priority="Standard",
                 assigned_picker=None, max_cart_capacity=35, total_orders=0, total_skus=0,
                 total_units=0, picked_units=0, estimated_distance_m=0.0,
                 unbatched_distance_m=0.0, distance_saved_m=0.0, scheduled_at=None,
                 deadline=None, started_at=None, completed_at=None, notes=None, created_at=None):
        self.id = str(id).strip()
        self.name = str(name).strip()
        self.status = str(status).strip() # Draft, Scheduled, Active, Paused, Completed, Cancelled
        self.strategy = str(strategy or "Hybrid").strip()
        self.priority = str(priority or "Standard").strip()
        self.assigned_picker = str(assigned_picker).strip() if assigned_picker else "Unassigned"
        self.max_cart_capacity = int(max_cart_capacity or 35)
        self.total_orders = int(total_orders or 0)
        self.total_skus = int(total_skus or 0)
        self.total_units = int(total_units or 0)
        self.picked_units = int(picked_units or 0)
        self.estimated_distance_m = float(estimated_distance_m or 0.0)
        self.unbatched_distance_m = float(unbatched_distance_m or 0.0)
        self.distance_saved_m = float(distance_saved_m or 0.0)
        self.scheduled_at = str(scheduled_at) if scheduled_at else None
        self.deadline = str(deadline) if deadline else None
        self.started_at = str(started_at) if started_at else None
        self.completed_at = str(completed_at) if completed_at else None
        self.notes = notes
        self.created_at = created_at

    @property
    def progress_pct(self):
        if self.total_units <= 0:
            return 100.0 if self.status == "Completed" else 0.0
        return min(100.0, round((self.picked_units / self.total_units) * 100.0, 1))

    @property
    def is_active(self):
        return self.status.lower() == "active"

    @property
    def is_completed(self):
        return self.status.lower() == "completed"

    @property
    def is_cancelled(self):
        return self.status.lower() == "cancelled"

    @property
    def travel_reduction_pct(self):
        if self.unbatched_distance_m <= 0:
            return 0.0
        return round((self.distance_saved_m / self.unbatched_distance_m) * 100.0, 1)

    def to_dict(self):
        return {
            "id": self.id,
            "wave_id": self.id,
            "name": self.name,
            "status": self.status,
            "strategy": self.strategy,
            "priority": self.priority,
            "assigned_picker": self.assigned_picker,
            "max_cart_capacity": self.max_cart_capacity,
            "total_orders": self.total_orders,
            "total_skus": self.total_skus,
            "total_units": self.total_units,
            "picked_units": self.picked_units,
            "progress_pct": self.progress_pct,
            "estimated_distance_m": round(self.estimated_distance_m, 1),
            "unbatched_distance_m": round(self.unbatched_distance_m, 1),
            "distance_saved_m": round(self.distance_saved_m, 1),
            "travel_reduction_pct": self.travel_reduction_pct,
            "scheduled_at": self.scheduled_at,
            "deadline": self.deadline,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "notes": self.notes,
            "created_at": str(self.created_at) if self.created_at else None
        }

class PickTask:
    """
    Consolidated SKU-level pick task representing a single stop in a Wave's picking sequence.
    Preserves order-level allocations for distribution at packing.
    """
    def __init__(self, id, wave_id, product_id, required_quantity, picked_quantity=0,
                 shelf_id=None, status="Pending", aisle_zone=None, sequence_order=0,
                 exception_reason=None, picked_at=None, order_allocations=None,
                 product_name=None, category=None):
        self.id = id
        self.wave_id = str(wave_id)
        self.product_id = int(product_id)
        self.required_quantity = int(required_quantity)
        self.picked_quantity = int(picked_quantity or 0)
        self.shelf_id = int(shelf_id) if shelf_id is not None else None
        self.status = str(status or "Pending").strip() # Pending, In Progress, Picked, Partial, Exception
        self.aisle_zone = aisle_zone or (f"Aisle {(shelf_id - 2) // 6 + 1}" if shelf_id and shelf_id > 1 else "Packing Hub")
        self.sequence_order = int(sequence_order or 0)
        self.exception_reason = exception_reason
        self.picked_at = str(picked_at) if picked_at else None
        self.order_allocations = order_allocations or {} # {order_id: quantity}
        self.product_name = product_name or f"Product #{product_id}"
        self.category = category or "General"

    @property
    def remaining_quantity(self):
        return max(0, self.required_quantity - self.picked_quantity)

    @property
    def is_picked(self):
        return self.picked_quantity >= self.required_quantity

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.id,
            "wave_id": self.wave_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "category": self.category,
            "sku": f"SKU-{self.product_id:04d}",
            "shelf_id": self.shelf_id,
            "shelf_label": f"Shelf {self.shelf_id}" if self.shelf_id else "Unassigned",
            "aisle_zone": self.aisle_zone,
            "required_quantity": self.required_quantity,
            "picked_quantity": self.picked_quantity,
            "remaining_quantity": self.remaining_quantity,
            "status": self.status,
            "sequence_order": self.sequence_order,
            "exception_reason": self.exception_reason,
            "picked_at": self.picked_at,
            "order_allocations": self.order_allocations
        }

class InventoryReservation:
    """
    Inventory reservation entity holding stock for an active Wave to prevent double-picking.
    """
    def __init__(self, id, wave_id, product_id, quantity, status="Reserved", created_at=None):
        self.id = id
        self.wave_id = str(wave_id)
        self.product_id = int(product_id)
        self.quantity = int(quantity)
        self.status = str(status or "Reserved") # Reserved, Fulfilled, Released
        self.created_at = created_at

    def to_dict(self):
        return {
            "id": self.id,
            "wave_id": self.wave_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "status": self.status,
            "created_at": str(self.created_at) if self.created_at else None
        }

class WaveException:
    """
    Audit record for picking shortages, inventory discrepancies, and blocked locations.
    """
    def __init__(self, id, wave_id, exception_type, details, task_id=None,
                 product_id=None, resolved=0, created_at=None):
        self.id = id
        self.wave_id = str(wave_id)
        self.task_id = task_id
        self.product_id = product_id
        self.exception_type = str(exception_type)
        self.details = str(details)
        self.resolved = bool(resolved)
        self.created_at = created_at

    def to_dict(self):
        return {
            "id": self.id,
            "wave_id": self.wave_id,
            "task_id": self.task_id,
            "product_id": self.product_id,
            "exception_type": self.exception_type,
            "details": self.details,
            "resolved": self.resolved,
            "created_at": str(self.created_at) if self.created_at else None
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
