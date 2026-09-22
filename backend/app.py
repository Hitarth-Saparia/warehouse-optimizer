"""
backend/app.py
Flask Web Application & REST API:
Provides clean endpoints connecting MySQL, OOP models, Graph algorithms, and Frontend.
Serves static frontend HTML/CSS directly.
"""

import os
import pymysql
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.models import Product, Shelf, Order
from backend.warehouse import Warehouse
from backend.layout_optimizer import LayoutOptimizer
from backend.route_optimizer import RouteOptimizer
from backend.comparison import calculate_comparison_statistics

# Base directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "frontend"))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

env_file = os.path.abspath(os.path.join(BACKEND_DIR, "..", ".env"))
if os.path.isfile(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if k not in os.environ:
                    os.environ[k] = v

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", 3306)),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASS", ""),
    "database": os.environ.get("DB_NAME", "wareopt"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True
}

def get_db():
    return pymysql.connect(**DB_CONFIG)

@app.errorhandler(pymysql.MySQLError)
def handle_mysql_error(err):
    return jsonify({
        "status": "error",
        "error": str(err),
        "hint": "MySQL error: Ensure MySQL is running on 127.0.0.1:3306 and run './run.sh --seed' to initialize database."
    }), 500


# Helper Functions to populate OOP Entities from MySQL
def fetch_all_shelves(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, distance_to_packing, capacity, current_load, x, y FROM shelves ORDER BY id ASC")
        rows = cur.fetchall()
        return [Shelf(**row) for row in rows]

def fetch_all_products(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.id, p.name, p.category, p.assigned_shelf_id,
                   COALESCE(SUM(s.units_sold), 0) AS pick_frequency
            FROM products p
            LEFT JOIN sales s ON p.id = s.product_id
            GROUP BY p.id, p.name, p.category, p.assigned_shelf_id
            ORDER BY pick_frequency DESC
        """)
        rows = cur.fetchall()
        return [Product(**row) for row in rows]

def fetch_warehouse(conn):
    shelves = fetch_all_shelves(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT from_shelf_id, to_shelf_id, distance FROM edges")
        edge_rows = cur.fetchall()
        edges = [(r["from_shelf_id"], r["to_shelf_id"], r["distance"]) for r in edge_rows]
    return Warehouse(shelves=shelves, edges=edges)

def fetch_all_orders(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, customer_name, status FROM orders ORDER BY id ASC")
        orders_raw = cur.fetchall()

        cur.execute("""
            SELECT oi.order_id, oi.product_id, oi.quantity, p.name, p.assigned_shelf_id
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            ORDER BY oi.id ASC
        """)
        items_raw = cur.fetchall()

    items_by_order = {}
    for it in items_raw:
        o_id = it["order_id"]
        if o_id not in items_by_order:
            items_by_order[o_id] = []
        items_by_order[o_id].append({
            "product_id": it["product_id"],
            "name": it["name"],
            "quantity": it["quantity"],
            "shelf_id": it["assigned_shelf_id"]
        })

    orders = []
    for o in orders_raw:
        orders.append(Order(
            id=o["id"],
            customer_name=o["customer_name"],
            status=o["status"],
            items=items_by_order.get(o["id"], [])
        ))
    return orders

# -------------------------------------------------------------
# REST API Routes
# -------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def get_products():
    """Returns all products with their assigned shelves and pick frequencies."""
    conn = get_db()
    try:
        products = fetch_all_products(conn)
        return jsonify([p.to_dict() for p in products])
    finally:
        conn.close()

@app.route("/api/shelves", methods=["GET"])
def get_shelves():
    """Returns all shelves with distance to packing and current capacities."""
    conn = get_db()
    try:
        shelves = fetch_all_shelves(conn)
        return jsonify([s.to_dict() for s in shelves])
    finally:
        conn.close()

@app.route("/api/orders", methods=["GET"])
def get_orders():
    """Returns all customer orders with line items."""
    conn = get_db()
    try:
        orders = fetch_all_orders(conn)
        return jsonify([o.to_dict() for o in orders])
    finally:
        conn.close()

@app.route("/api/warehouse/graph", methods=["GET"])
def get_warehouse_graph():
    """Returns graph nodes (shelves) and edges (distances) for visualization."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        return jsonify(warehouse.to_dict())
    finally:
        conn.close()

@app.route("/api/layout/optimize", methods=["POST"])
def optimize_layout():
    """
    Executes greedy layout optimization.
    Returns proposed old vs new shelf assignments without saving yet.
    """
    conn = get_db()
    try:
        products = fetch_all_products(conn)
        shelves = fetch_all_shelves(conn)
        optimizer = LayoutOptimizer()
        assignments, summary = optimizer.optimize(products, shelves)
        return jsonify({
            "status": "success",
            "summary": summary,
            "assignments": assignments
        })
    finally:
        conn.close()

@app.route("/api/layout/apply", methods=["POST"])
def apply_layout():
    """
    Applies the proposed assignments to the MySQL database.
    """
    data = request.get_json() or {}
    assignments = data.get("assignments")
    conn = get_db()
    try:
        if not assignments:
            # If not supplied in request body, re-run optimizer and apply
            products = fetch_all_products(conn)
            shelves = fetch_all_shelves(conn)
            optimizer = LayoutOptimizer()
            assignments, _ = optimizer.optimize(products, shelves)

        optimizer = LayoutOptimizer()
        optimizer.apply(conn, assignments)
        return jsonify({
            "status": "success",
            "message": f"Successfully updated shelf assignments for {len(assignments)} products in MySQL."
        })
    finally:
        conn.close()

@app.route("/api/orders/<int:order_id>/route", methods=["POST"])
def compute_order_route(order_id):
    """
    Computes the shortest picking route for the specified customer order.
    Uses Brute-Force Permutation for small orders (<8 items), or Nearest-Neighbor fallback.
    """
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        orders = fetch_all_orders(conn)
        order = next((o for o in orders if o.id == order_id), None)
        if not order:
            return jsonify({"error": f"Order #{order_id} not found"}), 404

        shelf_ids = [item["shelf_id"] for item in order.items if item["shelf_id"] is not None]
        router = RouteOptimizer(warehouse)
        route_result = router.solve_order_route(order_id, shelf_ids)
        route_result["customer_name"] = order.customer_name
        route_result["items"] = order.items
        return jsonify(route_result)
    finally:
        conn.close()

@app.route("/api/statistics", methods=["GET"])
def get_statistics():
    """
    Returns empirical before vs after distance comparisons across all orders.
    """
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        products = fetch_all_products(conn)
        shelves = fetch_all_shelves(conn)
        orders = fetch_all_orders(conn)

        stats = calculate_comparison_statistics(conn, warehouse, products, shelves, orders)
        stats["total_products"] = len(products)
        stats["total_shelves"] = len(shelves)
        stats["total_orders"] = len(orders)
        return jsonify(stats)
    finally:
        conn.close()

# -------------------------------------------------------------
# Frontend Static Routing
# -------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory(FRONTEND_DIR, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Warehouse Optimizer Server running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
