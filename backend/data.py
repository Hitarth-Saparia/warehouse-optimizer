"""
backend/data.py
Static and dynamic data interfaces for Warehouse Optimizer:
- PRODUCTS: catalog items
- SALES: pick velocity and sales records
- SHELVES: warehouse storage topology
- ORDERS: customer fulfillment orders with fleet specifications
- VEHICLES: delivery fleet assets
- WAREHOUSES: regional logistics hubs
"""

from backend.db import get_db
from backend.models import Product, Shelf, Order, Vehicle, WarehouseLocation

def get_shelves():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, distance_to_packing, capacity, current_load, x, y FROM shelves ORDER BY id ASC")
            rows = cur.fetchall()
            return [Shelf(r["id"], r["distance_to_packing"], r["capacity"], r["current_load"], r["x"], r["y"]) for r in rows]
    finally:
        conn.close()

def get_products():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.name, p.category, p.assigned_shelf_id, p.stock_quantity,
                       COALESCE(AVG(s.units_sold), 0) as pick_freq
                FROM products p
                LEFT JOIN sales s ON p.id = s.product_id
                GROUP BY p.id, p.name, p.category, p.assigned_shelf_id, p.stock_quantity
                ORDER BY p.id ASC
            """)
            rows = cur.fetchall()
            return [Product(r["id"], r["name"], r["category"], r["assigned_shelf_id"], r["pick_freq"], r["stock_quantity"]) for r in rows]
    finally:
        conn.close()

def get_orders():
    conn = get_db()
    try:
        from backend.app import fetch_all_orders
        return fetch_all_orders(conn)
    finally:
        conn.close()

def get_vehicles():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, vehicle_type, max_capacity, current_load, location, status, cost_per_km, fixed_cost, created_at FROM vehicles ORDER BY id ASC")
            rows = cur.fetchall()
            return [Vehicle(r["id"], r["name"], r["vehicle_type"], r["max_capacity"], r["current_load"], r["location"], r["status"], r["cost_per_km"], r["fixed_cost"], r["created_at"]) for r in rows]
    finally:
        conn.close()

def get_warehouses():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, location, coord_x, coord_y, service_zones FROM warehouses ORDER BY id ASC")
            rows = cur.fetchall()
            warehouses = []
            for r in rows:
                zones = [z.strip() for z in r["service_zones"].split(",") if z.strip()] if isinstance(r["service_zones"], str) else r["service_zones"]
                warehouses.append(WarehouseLocation(r["id"], r["name"], r["location"], r["coord_x"], r["coord_y"], zones))
            return warehouses
    finally:
        conn.close()

# Cached module-level exports
try:
    SHELVES = get_shelves()
    PRODUCTS = get_products()
    ORDERS = get_orders()
    VEHICLES = get_vehicles()
    WAREHOUSES = get_warehouses()
except Exception:
    SHELVES = []
    PRODUCTS = []
    ORDERS = []
    VEHICLES = []
    WAREHOUSES = []
