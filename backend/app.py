"""
backend/app.py
Flask Web Application & REST API:
Provides clean endpoints connecting MySQL, OOP models, Graph algorithms, and Frontend.
Serves static frontend HTML/CSS directly.
"""

import os
import re
from functools import wraps
import pymysql
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

from backend.models import (
    Product, Shelf, Order, User, AuditLog, Vehicle, WarehouseLocation, BalancingRun,
    Wave, PickTask, InventoryReservation, WaveException, InventoryTransaction, Notification
)
from backend.warehouse import Warehouse
from backend.layout_optimizer import LayoutOptimizer
from backend.route_optimizer import RouteOptimizer
from backend.comparison import calculate_comparison_statistics
from backend.batch_optimizer import BatchOptimizer
from backend.fleet_allocator import FleetAllocator
from backend.fleet_balancer import FleetBalancer
from backend.wave_manager import WaveManager
from backend.security import (
    hash_password,
    verify_password,
    generate_token,
    verify_token,
    login_rate_limiter
)

# Base directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "frontend"))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

from backend.db import get_db, get_active_db_type, DB_CONFIG

def parse_int_arg(param_name, default, min_val=None, max_val=None):
    """Safely extracts and validates an integer query parameter or JSON body value."""
    raw = request.args.get(param_name)
    if raw is None and request.is_json:
        body = request.get_json(silent=True) or {}
        raw = body.get(param_name)
    if raw is None:
        return default
    try:
        val = int(raw)
        if min_val is not None and val < min_val:
            return default
        if max_val is not None and val > max_val:
            return max_val
        return val
    except (ValueError, TypeError):
        return default

@app.route("/api/system/status", methods=["GET"])
def get_system_status():
    """Returns database backend status and engine metrics."""
    engine = get_active_db_type()
    return jsonify({
        "status": "healthy",
        "database_engine": engine,
        "host": DB_CONFIG["host"] if engine == "mysql" else "local_sqlite",
        "database": DB_CONFIG["database"] if engine == "mysql" else "wareopt.sqlite"
    })

@app.errorhandler(pymysql.MySQLError)
def handle_mysql_error(err):
    return jsonify({
        "status": "error",
        "error": str(err),
        "hint": "Database operation failed. The system supports automatic SQLite fallback."
    }), 500


# -------------------------------------------------------------
# Authentication & RBAC Middleware Helpers
# -------------------------------------------------------------

def get_client_ip():
    """Extracts client IP address supporting reverse proxies and direct connections."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def fetch_user_by_email(conn, email: str) -> User | None:
    """Queries user record by normalized lowercase email and hydrates User domain model."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, name, password_hash, salt, role, created_at, last_login FROM users WHERE email = %s",
            (email.strip().lower(),)
        )
        row = cur.fetchone()
        return User(**row) if row else None


def fetch_user_by_id(conn, user_id: int) -> User | None:
    """Queries user record by primary key and hydrates User domain model."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, name, password_hash, salt, role, created_at, last_login FROM users WHERE id = %s",
            (int(user_id),)
        )
        row = cur.fetchone()
        return User(**row) if row else None


def record_audit_log(conn, user_id, email, action, status, details=None, ip_address=None):
    """Inserts a security audit trail record into auth_audit_logs."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO auth_audit_logs (user_id, email, action, ip_address, status, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, email, action, ip_address or get_client_ip(), status, details))
        conn.commit()
    except Exception as e:
        print(f"[Audit Log Warning] Could not record auth audit event: {e}")


def require_auth(f):
    """
    Decorator Guard: Validates HMAC-SHA256 signed bearer token from Authorization header.
    Injects hydrated User entity into decorated handler as keyword argument `current_user`.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({
                "status": "error",
                "error": "Authentication required. Missing or malformed Authorization header."
            }), 401

        token = auth_header[7:].strip()
        claims = verify_token(token)
        if not claims or "sub" not in claims:
            return jsonify({
                "status": "error",
                "error": "Invalid, tampered, or expired session token."
            }), 401

        conn = get_db()
        try:
            user = fetch_user_by_id(conn, claims["sub"])
            if not user:
                return jsonify({
                    "status": "error",
                    "error": "Authenticated user record no longer exists."
                }), 401
        finally:
            conn.close()

        return f(*args, current_user=user, **kwargs)
    return decorated


def require_role(*allowed_roles):
    """
    Decorator Guard: Enforces Role-Based Access Control (RBAC).
    Verifies that the authenticated user possesses one of the allowed roles.
    """
    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, current_user=None, **kwargs):
            if current_user.role not in allowed_roles:
                return jsonify({
                    "status": "error",
                    "error": f"Access forbidden. Required role: {', '.join(allowed_roles)}. Current role: '{current_user.role}'."
                }), 403
            return f(*args, current_user=current_user, **kwargs)
        return decorated
    return decorator


# -------------------------------------------------------------
# Authentication REST API Endpoints
# -------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
@app.route("/api/register", methods=["POST"])
def auth_register():
    """
    Registers a new user account into the database with cryptographic salt + PBKDF2 hash.
    Enforces strict password criteria (min 8 chars, uppercase, lowercase, digit, special character).
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = (data.get("role") or "supervisor").strip().lower()
    client_ip = get_client_ip()

    if not name:
        return jsonify({"status": "error", "error": "Full name is required."}), 400
    if not email or "@" not in email:
        return jsonify({"status": "error", "error": "A valid email address is required."}), 400
    if role not in ["manager", "supervisor", "fleet", "guest"]:
        role = "supervisor"

    # Enforce password criteria: 8+ chars, upper, lower, number, special character
    if len(password) < 8:
        return jsonify({
            "status": "error",
            "error": "Password must be at least 8 characters long."
        }), 400
    if not re.search(r"[A-Z]", password):
        return jsonify({
            "status": "error",
            "error": "Password must include at least one uppercase letter (A-Z)."
        }), 400
    if not re.search(r"[a-z]", password):
        return jsonify({
            "status": "error",
            "error": "Password must include at least one lowercase letter (a-z)."
        }), 400
    if not re.search(r"[0-9]", password):
        return jsonify({
            "status": "error",
            "error": "Password must include at least one number (0-9)."
        }), 400
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_+=\[\]\\;'/`~]", password):
        return jsonify({
            "status": "error",
            "error": "Password must include at least one special character (!@#$%^&* etc.)."
        }), 400

    conn = get_db()
    try:
        existing = fetch_user_by_email(conn, email)
        if existing:
            return jsonify({
                "status": "error",
                "code": "EMAIL_ALREADY_EXISTS",
                "error": "An account with this email already exists. Please sign in instead."
            }), 409

        pwd_hash, salt = hash_password(password)

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, name, password_hash, salt, role) VALUES (%s, %s, %s, %s, %s)",
                (email, name, pwd_hash, salt, role)
            )
            user_id = cur.lastrowid
        conn.commit()

        record_audit_log(conn, user_id, email, "REGISTER", "SUCCESS", f"Registered new user '{name}' as {role}", client_ip)

        new_user = fetch_user_by_id(conn, user_id)
        if not new_user:
            new_user = User(id=user_id, email=email, name=name, password_hash=pwd_hash, salt=salt, role=role)

        token = generate_token({
            "sub": new_user.id,
            "email": new_user.email,
            "role": new_user.role,
            "name": new_user.name
        }, expires_in_seconds=43200)

        return jsonify({
            "status": "success",
            "message": f"Account created successfully for {name}!",
            "token": token,
            "user": new_user.to_dict()
        }), 201
    finally:
        conn.close()


@app.route("/api/auth/login", methods=["POST"])
@app.route("/api/login", methods=["POST"])
def auth_login():
    """
    Authenticates user credentials against PBKDF2 cryptographic hash & salt.
    Enforces sliding-window rate limiting to prevent brute-force credential stuffing.
    Returns: JSON with signed bearer token and user profile.
    Differentiates between non-existent accounts and invalid passwords.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    client_ip = get_client_ip()

    # Rate limiting guard (max 5 requests per 60s per IP+email pair)
    rate_key = f"{client_ip}:{email or 'anonymous'}"
    allowed, retry_after = login_rate_limiter.is_allowed(rate_key)
    if not allowed:
        return jsonify({
            "status": "error",
            "error": f"Too many failed login attempts. Rate limit exceeded. Try again in {retry_after} seconds.",
            "retry_after": retry_after
        }), 429

    if not email or not password:
        return jsonify({"status": "error", "error": "Both email and password are required."}), 400

    conn = get_db()
    try:
        user = fetch_user_by_email(conn, email)

        # Check if email is registered
        if not user:
            record_audit_log(conn, None, email, "LOGIN", "FAILURE", "Account does not exist", client_ip)
            return jsonify({
                "status": "error",
                "code": "ACCOUNT_NOT_FOUND",
                "error": "No account found with this email. Please create an account first!"
            }), 404

        # Constant-time password verification
        if not user.verify_password(password):
            record_audit_log(conn, user.id, email, "LOGIN", "FAILURE", "Invalid password", client_ip)
            return jsonify({
                "status": "error",
                "code": "INVALID_PASSWORD",
                "error": "Incorrect password. Please verify and try again."
            }), 401

        # Successful authentication: reset rate limiter for this user
        login_rate_limiter.reset(rate_key)
        record_audit_log(conn, user.id, email, "LOGIN", "SUCCESS", f"Authenticated as {user.role}", client_ip)

        # Update last_login timestamp
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user.id,))
        conn.commit()

        # Generate signed HMAC-SHA256 bearer token (12 hour expiration)
        token = generate_token({
            "sub": user.id,
            "email": user.email,
            "role": user.role,
            "name": user.name
        }, expires_in_seconds=43200)

        return jsonify({
            "status": "success",
            "token": token,
            "user": user.to_dict()
        })
    finally:
        conn.close()


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def auth_me(current_user: User):
    """Returns currently authenticated user profile based on bearer token."""
    return jsonify({
        "status": "success",
        "user": current_user.to_dict()
    })


@app.route("/api/auth/logout", methods=["POST"])
@require_auth
def auth_logout(current_user: User):
    """Logs the user logout event in the audit trail."""
    conn = get_db()
    try:
        record_audit_log(conn, current_user.id, current_user.email, "LOGOUT", "SUCCESS", "User signed out", get_client_ip())
        return jsonify({
            "status": "success",
            "message": "User session logged out successfully."
        })
    finally:
        conn.close()


@app.route("/api/auth/audit", methods=["GET"])
@require_role("manager")
def auth_audit_logs(current_user: User):
    """Administrative endpoint: Retrieves authentication audit logs (Manager only)."""
    limit = parse_int_arg("limit", default=50, min_val=1, max_val=200)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, email, action, ip_address, status, details, created_at
                FROM auth_audit_logs
                ORDER BY id DESC LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            logs = [AuditLog(**row).to_dict() for row in rows]
            return jsonify({
                "status": "success",
                "audit_logs": logs,
                "count": len(logs)
            })
    finally:
        conn.close()


# -------------------------------------------------------------
# Helper Functions to populate OOP Entities from MySQL
# -------------------------------------------------------------
def fetch_all_shelves(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, distance_to_packing, capacity, current_load, x, y FROM shelves ORDER BY id ASC")
        rows = cur.fetchall()
        return [Shelf(**row) for row in rows]

def create_notification(conn, type_, title, message, severity="info"):
    """Inserts a system notification if a duplicate unread one does not already exist."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM notifications 
                WHERE type = %s AND title = %s AND is_read = 0
                LIMIT 1
            """, (type_, title))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO notifications (type, title, message, severity, is_read)
                    VALUES (%s, %s, %s, %s, 0)
                """, (type_, title, message, severity))
                conn.commit()
    except Exception as e:
        print(f"[Notification Error] {e}")

def record_inventory_movement(conn, product_id, movement_type, qty_change, prev_qty, new_qty, reason="", ref_id="", user_email=""):
    """Records an audit log entry in inventory_transactions for physical stock movements."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO inventory_transactions 
                (product_id, movement_type, quantity_change, previous_quantity, new_quantity, reason, reference_id, user_email)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (product_id, movement_type, qty_change, prev_qty, new_qty, reason or "", str(ref_id or ""), user_email or "system@warehouse.io"))
            conn.commit()
    except Exception as e:
        print(f"[Inventory Movement Error] {e}")

def fetch_all_products(conn, include_archived=False):
    with conn.cursor() as cur:
        where_clause = "" if include_archived else "WHERE COALESCE(p.is_archived, 0) = 0"
        cur.execute(f"""
            SELECT p.id, p.name, p.category, p.assigned_shelf_id,
                   COALESCE(p.stock_quantity, 50) AS stock_quantity,
                   COALESCE(p.volume, 1.0) AS volume,
                   COALESCE(p.sku, '') AS sku,
                   COALESCE(p.reorder_threshold, 15) AS reorder_threshold,
                   COALESCE(p.unit_price, 19.99) AS unit_price,
                   COALESCE(p.is_archived, 0) AS is_archived,
                   COALESCE(SUM(s.units_sold), 0) AS pick_frequency
            FROM products p
            LEFT JOIN sales s ON p.id = s.product_id
            {where_clause}
            GROUP BY p.id, p.name, p.category, p.assigned_shelf_id, p.stock_quantity, p.volume, p.sku, p.reorder_threshold, p.unit_price, p.is_archived
            ORDER BY pick_frequency DESC
        """)
        rows = cur.fetchall()
        return [Product(**row) for row in rows]

BLOCKED_CORRIDORS = set()  # set of (min(u, v), max(u, v))
CORRIDOR_PENALTIES = {}    # (min(u, v), max(u, v)) -> float

def fetch_warehouse(conn):
    shelves = fetch_all_shelves(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT from_shelf_id, to_shelf_id, distance FROM edges")
        edge_rows = cur.fetchall()
        edges = [(r["from_shelf_id"], r["to_shelf_id"], r["distance"]) for r in edge_rows]
    w = Warehouse(shelves=shelves, edges=edges)
    for u, v in BLOCKED_CORRIDORS:
        w.block_corridor(u, v)
    for (u, v), p in CORRIDOR_PENALTIES.items():
        w.set_corridor_penalty(u, v, p)
    return w

def fetch_all_orders(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM orders ORDER BY id ASC")
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
            items=items_by_order.get(o["id"], []),
            weight=o.get("weight"),
            destination_zone=o.get("destination_zone", "Zone A - Downtown"),
            priority=o.get("priority", "Standard"),
            deadline=o.get("deadline", "18:00"),
            warehouse_id=o.get("warehouse_id", "WH-01"),
            assigned_vehicle_id=o.get("assigned_vehicle_id"),
            total_amount=o.get("total_amount", 0.0),
            created_at=o.get("created_at")
        ))
    return orders

# -------------------------------------------------------------
# REST API Routes: Products & Inventory Management
# -------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
def get_products():
    """
    Returns products catalog with filtering by category, search term,
    low stock status, and archive visibility.
    """
    category = request.args.get("category")
    search = request.args.get("search", "").strip().lower()
    include_archived = request.args.get("include_archived", "").lower() in ("true", "1", "yes")
    low_stock_only = request.args.get("low_stock", "").lower() in ("true", "1", "yes")

    conn = get_db()
    try:
        products = fetch_all_products(conn, include_archived=include_archived)
        if category and category.upper() != "ALL":
            products = [p for p in products if p.category.lower() == category.lower()]
        if search:
            products = [p for p in products if search in p.name.lower() or search in (p.sku or "").lower()]
        if low_stock_only:
            products = [p for p in products if p.is_low_stock]

        return jsonify([p.to_dict() for p in products])
    finally:
        conn.close()

@app.route("/api/products", methods=["POST"])
def create_product():
    """
    Adds a new product to the warehouse catalog.
    Validates name, category, shelf assignment capacity, and SKU uniqueness.
    Logs an initial 'INBOUND' stock movement.
    """
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()

    if not name:
        return jsonify({"error": "Product name is required", "status": "error"}), 400
    if not category:
        return jsonify({"error": "Product category is required", "status": "error"}), 400

    stock_quantity = parse_int_arg("stock_quantity", default=50, min_val=0, max_val=10000)
    reorder_threshold = parse_int_arg("reorder_threshold", default=15, min_val=0, max_val=5000)
    
    try:
        volume = float(data.get("volume", 1.0))
        if volume <= 0:
            volume = 1.0
    except (ValueError, TypeError):
        volume = 1.0

    try:
        unit_price = float(data.get("unit_price", 19.99))
        if unit_price <= 0:
            unit_price = 19.99
    except (ValueError, TypeError):
        unit_price = 19.99

    assigned_shelf_id = data.get("assigned_shelf_id")
    if assigned_shelf_id not in (None, "", "null"):
        try:
            assigned_shelf_id = int(assigned_shelf_id)
        except (ValueError, TypeError):
            return jsonify({"error": "assigned_shelf_id must be a valid integer", "status": "error"}), 400
    else:
        assigned_shelf_id = None

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Check shelf capacity if shelf provided
            if assigned_shelf_id is not None:
                cur.execute("SELECT id, capacity, current_load FROM shelves WHERE id = %s", (assigned_shelf_id,))
                shelf = cur.fetchone()
                if not shelf:
                    return jsonify({"error": f"Shelf #{assigned_shelf_id} does not exist", "status": "error"}), 400
                if shelf["current_load"] >= shelf["capacity"]:
                    return jsonify({
                        "error": f"Shelf #{assigned_shelf_id} is already at full capacity ({shelf['current_load']}/{shelf['capacity']} items)",
                        "status": "error"
                    }), 400

            # Determine SKU
            cat_pfx = {"Heavy": "HV", "Fragile": "FR", "Electronics": "EL", "Tools": "TL", "Fasteners": "FA", "Safety": "SF"}
            custom_sku = str(data.get("sku", "")).strip()
            if custom_sku:
                cur.execute("SELECT id FROM products WHERE sku = %s", (custom_sku,))
                if cur.fetchone():
                    return jsonify({"error": f"SKU '{custom_sku}' already exists in catalog", "status": "error"}), 400
                final_sku = custom_sku
            else:
                cur.execute("SELECT COUNT(*) AS cnt FROM products WHERE category = %s", (category,))
                c_row = cur.fetchone()
                cnt = (c_row["cnt"] if isinstance(c_row, dict) else c_row[0]) + 1
                final_sku = f"SKU-{cat_pfx.get(category, 'GN')}-{cnt:03d}"

            cur.execute("""
                INSERT INTO products (name, category, assigned_shelf_id, stock_quantity, volume, sku, reorder_threshold, unit_price, is_archived)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
            """, (name, category, assigned_shelf_id, stock_quantity, volume, final_sku, reorder_threshold, unit_price))
            new_id = cur.lastrowid

            # Increment shelf load if assigned
            if assigned_shelf_id is not None:
                cur.execute("UPDATE shelves SET current_load = current_load + 1 WHERE id = %s", (assigned_shelf_id,))

            conn.commit()

            # Record initial inbound inventory transaction
            user_email = _get_request_user_email()
            record_inventory_movement(
                conn, new_id, "INBOUND", stock_quantity, 0, stock_quantity,
                reason="Initial product receipt", user_email=user_email
            )

            # Security audit
            record_audit_log(conn, None, user_email, "PRODUCT_CREATE", "SUCCESS", f"Created product #{new_id} ({name}, {final_sku})")

        return jsonify({
            "status": "success",
            "message": f"Product '{name}' ({final_sku}) successfully added to catalog.",
            "product": {
                "id": new_id,
                "name": name,
                "category": category,
                "assigned_shelf_id": assigned_shelf_id,
                "stock_quantity": stock_quantity,
                "volume": volume,
                "sku": final_sku,
                "reorder_threshold": reorder_threshold,
                "unit_price": unit_price,
                "is_archived": 0,
                "is_low_stock": stock_quantity <= reorder_threshold
            }
        }), 201
    finally:
        conn.close()

@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product_detail(product_id):
    """Returns single product details and recent inventory movement history."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.name, p.category, p.assigned_shelf_id,
                       COALESCE(p.stock_quantity, 50) AS stock_quantity,
                       COALESCE(p.volume, 1.0) AS volume,
                       COALESCE(p.sku, '') AS sku,
                       COALESCE(p.reorder_threshold, 15) AS reorder_threshold,
                       COALESCE(p.unit_price, 19.99) AS unit_price,
                       COALESCE(p.is_archived, 0) AS is_archived,
                       COALESCE(SUM(s.units_sold), 0) AS pick_frequency
                FROM products p
                LEFT JOIN sales s ON p.id = s.product_id
                WHERE p.id = %s
                GROUP BY p.id, p.name, p.category, p.assigned_shelf_id, p.stock_quantity, p.volume, p.sku, p.reorder_threshold, p.unit_price, p.is_archived
            """, (product_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": f"Product #{product_id} not found", "status": "error"}), 404

            cur.execute("""
                SELECT id, movement_type, quantity_change, previous_quantity, new_quantity, reason, reference_id, user_email, created_at
                FROM inventory_transactions
                WHERE product_id = %s
                ORDER BY id DESC LIMIT 20
            """, (product_id,))
            tx_rows = cur.fetchall()

        prod = Product(**row)
        return jsonify({
            "status": "success",
            "product": prod.to_dict(),
            "transactions": tx_rows
        })
    finally:
        conn.close()

@app.route("/api/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    """
    Updates product catalog attributes: name, category, shelf assignment, volume,
    reorder threshold, and unit price. Handles shelf load migration.
    """
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
            current = cur.fetchone()
            if not current:
                return jsonify({"error": f"Product #{product_id} not found", "status": "error"}), 404

            name = str(data.get("name", current["name"])).strip()
            category = str(data.get("category", current["category"])).strip()
            volume = float(data.get("volume", current.get("volume", 1.0)))
            unit_price = float(data.get("unit_price", current.get("unit_price", 19.99)))
            reorder_threshold = int(data.get("reorder_threshold", current.get("reorder_threshold", 15)))

            # Handle shelf re-assignment
            new_shelf_id = data.get("assigned_shelf_id", current["assigned_shelf_id"])
            if new_shelf_id in ("", "null"):
                new_shelf_id = None
            elif new_shelf_id is not None:
                new_shelf_id = int(new_shelf_id)

            old_shelf_id = current["assigned_shelf_id"]

            if new_shelf_id != old_shelf_id:
                if new_shelf_id is not None:
                    cur.execute("SELECT id, capacity, current_load FROM shelves WHERE id = %s", (new_shelf_id,))
                    target_shelf = cur.fetchone()
                    if not target_shelf:
                        return jsonify({"error": f"Shelf #{new_shelf_id} not found", "status": "error"}), 400
                    if target_shelf["current_load"] >= target_shelf["capacity"]:
                        return jsonify({
                            "error": f"Shelf #{new_shelf_id} is full ({target_shelf['current_load']}/{target_shelf['capacity']})",
                            "status": "error"
                        }), 400
                    cur.execute("UPDATE shelves SET current_load = current_load + 1 WHERE id = %s", (new_shelf_id,))

                if old_shelf_id is not None:
                    cur.execute("UPDATE shelves SET current_load = GREATEST(0, current_load - 1) WHERE id = %s", (old_shelf_id,))

            cur.execute("""
                UPDATE products 
                SET name = %s, category = %s, assigned_shelf_id = %s, volume = %s, unit_price = %s, reorder_threshold = %s
                WHERE id = %s
            """, (name, category, new_shelf_id, volume, unit_price, reorder_threshold, product_id))
            conn.commit()

            user_email = _get_request_user_email()
            record_audit_log(conn, None, user_email, "PRODUCT_UPDATE", "SUCCESS", f"Updated product #{product_id} ({name})")

        return jsonify({
            "status": "success",
            "message": f"Product #{product_id} ('{name}') updated successfully."
        })
    finally:
        conn.close()

@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def archive_product(product_id):
    """
    Soft-archives a catalog item. Releases shelf space and marks is_archived = 1.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, assigned_shelf_id FROM products WHERE id = %s", (product_id,))
            prod = cur.fetchone()
            if not prod:
                return jsonify({"error": f"Product #{product_id} not found", "status": "error"}), 404

            # Release shelf load if currently slotted
            if prod["assigned_shelf_id"]:
                cur.execute("UPDATE shelves SET current_load = GREATEST(0, current_load - 1) WHERE id = %s", (prod["assigned_shelf_id"],))

            cur.execute("UPDATE products SET is_archived = 1 WHERE id = %s", (product_id,))
            conn.commit()

            user_email = _get_request_user_email()
            record_audit_log(conn, None, user_email, "PRODUCT_ARCHIVE", "SUCCESS", f"Archived product #{product_id} ({prod['name']})")

        return jsonify({
            "status": "success",
            "message": f"Product '{prod['name']}' #{product_id} has been archived."
        })
    finally:
        conn.close()

@app.route("/api/products/<int:product_id>/restore", methods=["POST"])
def restore_product(product_id):
    """Restores an archived product to the active catalog."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, assigned_shelf_id FROM products WHERE id = %s", (product_id,))
            prod = cur.fetchone()
            if not prod:
                return jsonify({"error": f"Product #{product_id} not found", "status": "error"}), 404

            cur.execute("UPDATE products SET is_archived = 0 WHERE id = %s", (product_id,))
            conn.commit()

            user_email = _get_request_user_email()
            record_audit_log(conn, None, user_email, "PRODUCT_RESTORE", "SUCCESS", f"Restored product #{product_id} ({prod['name']})")

        return jsonify({
            "status": "success",
            "message": f"Product '{prod['name']}' restored to active catalog."
        })
    finally:
        conn.close()

@app.route("/api/products/<int:product_id>/stock", methods=["POST"])
def adjust_product_stock(product_id):
    """
    Adjusts physical inventory stock (+ or -) with mandatory transaction logging.
    Auto-triggers a LOW_STOCK notification if remaining stock <= reorder threshold.
    """
    data = request.get_json(silent=True) or {}
    try:
        qty_change = int(data.get("quantity_change", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "quantity_change must be a valid non-zero integer", "status": "error"}), 400

    if qty_change == 0:
        return jsonify({"error": "quantity_change cannot be zero", "status": "error"}), 400

    movement_type = str(data.get("movement_type", "ADJUSTMENT" if qty_change < 0 else "RESTOCK")).upper()
    reason = str(data.get("reason", "Manual inventory adjustment")).strip()

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, sku, stock_quantity, reorder_threshold FROM products WHERE id = %s", (product_id,))
            prod = cur.fetchone()
            if not prod:
                return jsonify({"error": f"Product #{product_id} not found", "status": "error"}), 404

            prev_stock = prod["stock_quantity"]
            new_stock = prev_stock + qty_change
            if new_stock < 0:
                return jsonify({
                    "error": f"Cannot deduct {abs(qty_change)} units: current stock is only {prev_stock} units",
                    "status": "error"
                }), 400

            cur.execute("UPDATE products SET stock_quantity = %s WHERE id = %s", (new_stock, product_id))
            conn.commit()

            user_email = _get_request_user_email()
            record_inventory_movement(
                conn, product_id, movement_type, qty_change, prev_stock, new_stock,
                reason=reason, user_email=user_email
            )

            # Check low-stock threshold alert
            if new_stock <= prod["reorder_threshold"]:
                create_notification(
                    conn, "LOW_STOCK",
                    f"Low Stock: {prod['name']}",
                    f"Product '{prod['name']}' ({prod['sku']}) has {new_stock} units remaining (threshold: {prod['reorder_threshold']}).",
                    severity="warning"
                )

            record_audit_log(
                conn, None, user_email, "STOCK_ADJUSTMENT", "SUCCESS",
                f"Adjusted stock for #{product_id} by {qty_change} (New: {new_stock})"
            )

        return jsonify({
            "status": "success",
            "message": f"Stock for '{prod['name']}' updated from {prev_stock} to {new_stock}.",
            "previous_quantity": prev_stock,
            "new_quantity": new_stock,
            "quantity_change": qty_change
        })
    finally:
        conn.close()

@app.route("/api/inventory/transactions", methods=["GET"])
def get_inventory_transactions():
    """
    Returns full chronological audit log of all warehouse physical inventory movements.
    Supports filtering by product_id and movement_type.
    """
    limit = parse_int_arg("limit", default=50, min_val=1, max_val=200)
    offset = parse_int_arg("offset", default=0, min_val=0)
    prod_id = request.args.get("product_id")
    movement_type = request.args.get("movement_type")

    conn = get_db()
    try:
        where_clauses = []
        params = []
        if prod_id:
            where_clauses.append("it.product_id = %s")
            params.append(int(prod_id))
        if movement_type:
            where_clauses.append("it.movement_type = %s")
            params.append(movement_type.upper())

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT it.id, it.product_id, it.movement_type, it.quantity_change,
                       it.previous_quantity, it.new_quantity, it.reason, it.reference_id,
                       it.user_email, it.created_at, p.name AS product_name, p.sku
                FROM inventory_transactions it
                LEFT JOIN products p ON it.product_id = p.id
                {where_sql}
                ORDER BY it.id DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            rows = cur.fetchall()

            cur.execute(f"SELECT COUNT(*) AS total FROM inventory_transactions it {where_sql}", params)
            t_row = cur.fetchone()
            total = t_row["total"] if isinstance(t_row, dict) else t_row[0]

        return jsonify({
            "status": "success",
            "total": total,
            "count": len(rows),
            "transactions": rows
        })
    finally:
        conn.close()

# -------------------------------------------------------------
# REST API Routes: Notifications System
# -------------------------------------------------------------

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    """Returns persistent warehouse system and operational notifications with unread counts."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, type, title, message, severity, is_read, created_at
                FROM notifications
                ORDER BY id DESC
                LIMIT 50
            """)
            items = cur.fetchall()

            cur.execute("SELECT COUNT(*) AS unread FROM notifications WHERE is_read = 0")
            u_row = cur.fetchone()
            unread = u_row["unread"] if isinstance(u_row, dict) else u_row[0]

        return jsonify({
            "status": "success",
            "unread_count": unread,
            "notifications": items
        })
    finally:
        conn.close()

@app.route("/api/notifications/<int:notification_id>/read", methods=["POST", "PATCH"])
def mark_notification_read(notification_id):
    """Marks a notification as read."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (notification_id,))
            conn.commit()
        return jsonify({"status": "success", "message": f"Notification #{notification_id} marked as read."})
    finally:
        conn.close()

@app.route("/api/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    """Marks all operational notifications as read."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
            conn.commit()
        return jsonify({"status": "success", "message": "All notifications marked as read."})
    finally:
        conn.close()

@app.route("/api/notifications/<int:notification_id>", methods=["DELETE"])
def dismiss_notification(notification_id):
    """Deletes/dismisses an operational notification."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notifications WHERE id = %s", (notification_id,))
            conn.commit()
        return jsonify({"status": "success", "message": f"Notification #{notification_id} dismissed."})
    finally:
        conn.close()

# -------------------------------------------------------------
# REST API Routes: Reports & Analytics
# -------------------------------------------------------------

@app.route("/api/reports/analytics", methods=["GET"])
def get_reports_analytics():
    """
    Computes complete operational analytics from real database tables:
    inventory valuation, order status distributions, picking throughput, and fleet utilization.
    Optional format=csv generates a downloadable executive report.
    """
    export_format = request.args.get("format", "").lower()
    conn = get_db()
    try:
        products = fetch_all_products(conn, include_archived=True)
        active_products = [p for p in products if not p.is_archived]
        orders = fetch_all_orders(conn)
        shelves = fetch_all_shelves(conn)

        total_units = sum(p.stock_quantity for p in active_products)
        total_value = round(sum(p.stock_quantity * p.unit_price for p in active_products), 2)
        low_stock_items = [p for p in active_products if p.is_low_stock]

        # Category breakdown
        cat_stats = {}
        for p in active_products:
            c = p.category
            if c not in cat_stats:
                cat_stats[c] = {"count": 0, "units": 0, "value": 0.0, "pick_freq": 0}
            cat_stats[c]["count"] += 1
            cat_stats[c]["units"] += p.stock_quantity
            cat_stats[c]["value"] = round(cat_stats[c]["value"] + p.stock_quantity * p.unit_price, 2)
            cat_stats[c]["pick_freq"] += int(p.pick_frequency)

        # Order distribution
        order_status_dist = {"Pending": 0, "Picking": 0, "Completed": 0, "Cancelled": 0}
        for o in orders:
            st = o.status.title() if o.status else "Pending"
            order_status_dist[st] = order_status_dist.get(st, 0) + 1

        # Fleet summary
        balancer = FleetBalancer()
        fleet_summary = balancer.get_dashboard_summary()

        data_payload = {
            "status": "success",
            "inventory": {
                "active_skus": len(active_products),
                "archived_skus": len(products) - len(active_products),
                "total_units": total_units,
                "total_valuation": total_value,
                "low_stock_count": len(low_stock_items),
                "categories": cat_stats
            },
            "orders": {
                "total_orders": len(orders),
                "status_breakdown": order_status_dist
            },
            "warehouse": {
                "total_shelves": len(shelves),
                "storage_bays": len(shelves) - 1,
                "total_capacity": sum(s.capacity for s in shelves if s.id > 1),
                "current_load": sum(s.current_load for s in shelves if s.id > 1)
            },
            "fleet": {
                "total_vehicles": fleet_summary["metrics"]["total_vehicles"],
                "utilization_pct": fleet_summary["metrics"]["fleet_utilization_pct"],
                "active_assignments": fleet_summary["metrics"]["assigned_orders"]
            }
        }

        if export_format == "csv":
            csv_lines = [
                "Category,SKU Count,Units In Stock,Total Value ($),Avg Pick Frequency",
            ]
            for cat, st in cat_stats.items():
                avg_pf = round(st["pick_freq"] / max(1, st["count"]), 1)
                csv_lines.append(f'"{cat}",{st["count"]},{st["units"]},{st["value"]},{avg_pf}')
            csv_lines.append("")
            csv_lines.append("Order Status,Count")
            for st, cnt in order_status_dist.items():
                csv_lines.append(f'"{st}",{cnt}')

            return Response(
                "\n".join(csv_lines),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=warehouse_analytics_report.csv"}
            )

        return jsonify(data_payload)
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

def recalculate_warehouse_distances(conn, w=None):
    """Recalculates Dijkstra shortest distance to packing station (Shelf 1) for all shelves."""
    if w is None:
        w = fetch_warehouse(conn)
    with conn.cursor() as cur:
        for s_id in list(w.shelves.keys()):
            if s_id == 1:
                cur.execute("UPDATE shelves SET distance_to_packing = 0.0 WHERE id = 1")
            else:
                d, _ = w.dijkstra(1, s_id)
                dist = round(d, 1) if d != float('inf') else 999.0
                cur.execute("UPDATE shelves SET distance_to_packing = %s WHERE id = %s", (dist, s_id))

@app.route("/api/warehouse/graph", methods=["GET"])
def get_warehouse_graph():
    """Returns graph nodes (shelves) and edges (distances) for visualization."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        graph_dict = warehouse.to_dict()
        graph_dict["blocked_corridors"] = warehouse.get_blocked_corridors()
        
        # Attach slotted products information for each shelf
        products = fetch_all_products(conn)
        products_by_shelf = {}
        for p in products:
            if p.assigned_shelf_id is not None:
                if p.assigned_shelf_id not in products_by_shelf:
                    products_by_shelf[p.assigned_shelf_id] = []
                products_by_shelf[p.assigned_shelf_id].append(p.to_dict())
        graph_dict["products_by_shelf"] = products_by_shelf
        return jsonify(graph_dict)
    finally:
        conn.close()

@app.route("/api/warehouse/graph/save", methods=["POST"])
def save_warehouse_graph():
    """
    Saves an edited warehouse graph layout (nodes and edges) and recomputes shortest path distances.
    """
    data = request.get_json() or {}
    nodes_data = data.get("nodes", [])
    edges_data = data.get("edges", [])

    if not nodes_data:
        return jsonify({"error": "Graph must contain at least one node."}), 400

    has_shelf_1 = any(int(n.get("id", 0)) == 1 for n in nodes_data)
    if not has_shelf_1:
        return jsonify({"error": "Warehouse must include Shelf 1 (Packing/Dispatch Dock)."}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            submitted_ids = set()
            for n in nodes_data:
                s_id = int(n["id"])
                submitted_ids.add(s_id)
                x = int(round(float(n.get("x", 0))))
                y = int(round(float(n.get("y", 0))))
                cap = int(n.get("capacity", 999 if s_id == 1 else 5))
                cur_load = int(n.get("current_load", 0))
                dist = float(n.get("distance_to_packing", 0.0))

                cur.execute("SELECT id FROM shelves WHERE id = %s", (s_id,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("""
                        UPDATE shelves
                        SET x = %s, y = %s, capacity = %s, current_load = %s, distance_to_packing = %s
                        WHERE id = %s
                    """, (x, y, cap, cur_load, dist, s_id))
                else:
                    cur.execute("""
                        INSERT INTO shelves (id, distance_to_packing, capacity, current_load, x, y)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (s_id, dist, cap, cur_load, x, y))

            # Delete any shelves that were removed (except Shelf 1)
            cur.execute("SELECT id FROM shelves")
            all_db_shelves = [r["id"] for r in cur.fetchall()]
            for db_id in all_db_shelves:
                if db_id not in submitted_ids and db_id != 1:
                    cur.execute("UPDATE products SET assigned_shelf_id = NULL WHERE assigned_shelf_id = %s", (db_id,))
                    cur.execute("DELETE FROM edges WHERE from_shelf_id = %s OR to_shelf_id = %s", (db_id, db_id))
                    cur.execute("DELETE FROM shelves WHERE id = %s", (db_id,))

            # Synchronize edges
            cur.execute("DELETE FROM edges")
            edge_pairs_seen = set()
            new_edges = []
            for e in edges_data:
                u = int(e["from_shelf_id"])
                v = int(e["to_shelf_id"])
                dist = float(e.get("distance", 1.0))
                if u == v or u not in submitted_ids or v not in submitted_ids:
                    continue
                pair = (min(u, v), max(u, v))
                if pair not in edge_pairs_seen:
                    edge_pairs_seen.add(pair)
                    new_edges.append((u, v, dist))
                    new_edges.append((v, u, dist))

            if new_edges:
                cur.executemany(
                    "INSERT INTO edges (from_shelf_id, to_shelf_id, distance) VALUES (%s, %s, %s)",
                    new_edges
                )

        recalculate_warehouse_distances(conn)

        user_email = _get_request_user_email()
        record_audit_log(conn, None, user_email, "GRAPH_UPDATE", "SUCCESS", f"Updated warehouse graph: {len(submitted_ids)} nodes, {len(edge_pairs_seen)} edges")
        conn.commit()

        updated_w = fetch_warehouse(conn)
        updated_w._invalidate_cache()
        res_dict = updated_w.to_dict()
        res_dict["blocked_corridors"] = updated_w.get_blocked_corridors()
        return jsonify({
            "status": "success",
            "message": f"Warehouse graph saved: {len(submitted_ids)} nodes, {len(edge_pairs_seen)} edges. Shortest paths recomputed.",
            "graph": res_dict
        })
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": f"Failed to save warehouse graph: {str(exc)}"}), 500
    finally:
        conn.close()

@app.route("/api/warehouse/graph/reset", methods=["POST"])
def reset_warehouse_graph_api():
    """Resets the warehouse topology to standard factory default grid."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM edges")
            cur.execute("UPDATE products SET assigned_shelf_id = NULL WHERE assigned_shelf_id > 25")
            cur.execute("DELETE FROM shelves WHERE id > 25")

            shelves_data = [(1, 0.0, 999, 0, 80, 260)]
            y_coords = [80, 150, 220, 290, 360, 430]
            s_id = 2
            aisle_x = [220, 380, 540, 700]
            aisle_base_dist = [8.0, 16.0, 24.0, 32.0]
            for a_idx, x in enumerate(aisle_x):
                base_d = aisle_base_dist[a_idx]
                for row_idx, y in enumerate(y_coords):
                    dist = round(base_d + abs(y - 260) * 0.06 + row_idx * 1.5, 1)
                    shelves_data.append((s_id, dist, 5, 0, x, y))
                    s_id += 1

            for sid, dist, cap, cur_l, x, y in shelves_data:
                cur.execute("SELECT id FROM shelves WHERE id = %s", (sid,))
                if cur.fetchone():
                    cur.execute("""
                        UPDATE shelves SET distance_to_packing=%s, capacity=%s, current_load=%s, x=%s, y=%s WHERE id=%s
                    """, (dist, cap, cur_l, x, y, sid))
                else:
                    cur.execute("""
                        INSERT INTO shelves (id, distance_to_packing, capacity, current_load, x, y) VALUES (%s, %s, %s, %s, %s, %s)
                    """, (sid, dist, cap, cur_l, x, y))

            edges = [(1, 4, 10.0), (1, 5, 10.0), (1, 2, 14.0)]
            for a in range(4):
                start_s = 2 + a * 6
                for i in range(5):
                    edges.append((start_s + i, start_s + i + 1, 6.0))
            edges.extend([
                (2, 8, 12.0), (8, 14, 12.0), (14, 20, 12.0),
                (5, 11, 12.0), (11, 17, 12.0), (17, 23, 12.0),
                (7, 13, 12.0), (13, 19, 12.0), (19, 25, 12.0)
            ])
            full_edges = []
            for u, v, w in edges:
                full_edges.append((u, v, w))
                full_edges.append((v, u, w))
            cur.executemany("INSERT INTO edges (from_shelf_id, to_shelf_id, distance) VALUES (%s, %s, %s)", full_edges)

        BLOCKED_CORRIDORS.clear()
        CORRIDOR_PENALTIES.clear()
        recalculate_warehouse_distances(conn)
        conn.commit()

        updated_w = fetch_warehouse(conn)
        res_dict = updated_w.to_dict()
        res_dict["blocked_corridors"] = updated_w.get_blocked_corridors()
        return jsonify({
            "status": "success",
            "message": "Warehouse graph restored to factory default layout.",
            "graph": res_dict
        })
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": f"Failed to reset graph: {str(exc)}"}), 500
    finally:
        conn.close()

@app.route("/api/warehouse/shelves", methods=["POST"])
def add_warehouse_shelf():
    """Adds a new shelf location to the warehouse."""
    data = request.get_json() or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # find next available shelf id if not provided
            s_id = data.get("id")
            if not s_id:
                cur.execute("SELECT MAX(id) as max_id FROM shelves")
                max_row = cur.fetchone()
                s_id = (max_row["max_id"] or 1) + 1
            else:
                s_id = int(s_id)

            x = int(round(float(data.get("x", 200))))
            y = int(round(float(data.get("y", 200))))
            capacity = int(data.get("capacity", 5))
            dist = float(data.get("distance_to_packing", 0.0))

            cur.execute("""
                INSERT INTO shelves (id, distance_to_packing, capacity, current_load, x, y)
                VALUES (%s, %s, %s, 0, %s, %s)
            """, (s_id, dist, capacity, x, y))
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Shelf {s_id} added successfully.",
            "shelf": {"id": s_id, "x": x, "y": y, "capacity": capacity, "current_load": 0, "distance_to_packing": dist}
        }), 201
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": f"Failed to add shelf: {str(exc)}"}), 500
    finally:
        conn.close()

@app.route("/api/warehouse/shelves/<int:shelf_id>", methods=["PUT", "DELETE"])
def manage_warehouse_shelf(shelf_id):
    """Updates or deletes a specific shelf."""
    if shelf_id == 1 and request.method == "DELETE":
        return jsonify({"error": "Cannot delete Shelf 1 (Packing/Dispatch Dock)."}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if request.method == "DELETE":
                cur.execute("UPDATE products SET assigned_shelf_id = NULL WHERE assigned_shelf_id = %s", (shelf_id,))
                cur.execute("DELETE FROM edges WHERE from_shelf_id = %s OR to_shelf_id = %s", (shelf_id, shelf_id))
                cur.execute("DELETE FROM shelves WHERE id = %s", (shelf_id,))
                recalculate_warehouse_distances(conn)
                conn.commit()
                return jsonify({"status": "success", "message": f"Shelf {shelf_id} deleted."})

            # PUT update
            data = request.get_json() or {}
            x = data.get("x")
            y = data.get("y")
            capacity = data.get("capacity")
            dist = data.get("distance_to_packing")

            cur.execute("SELECT id, x, y, capacity, distance_to_packing, current_load FROM shelves WHERE id = %s", (shelf_id,))
            shelf = cur.fetchone()
            if not shelf:
                return jsonify({"error": f"Shelf {shelf_id} not found."}), 404

            new_x = int(round(float(x))) if x is not None else shelf["x"]
            new_y = int(round(float(y))) if y is not None else shelf["y"]
            new_cap = int(capacity) if capacity is not None else shelf["capacity"]
            new_dist = float(dist) if dist is not None else shelf["distance_to_packing"]

            cur.execute("""
                UPDATE shelves
                SET x = %s, y = %s, capacity = %s, distance_to_packing = %s
                WHERE id = %s
            """, (new_x, new_y, new_cap, new_dist, shelf_id))
            conn.commit()

            return jsonify({
                "status": "success",
                "message": f"Shelf {shelf_id} updated.",
                "shelf": {"id": shelf_id, "x": new_x, "y": new_y, "capacity": new_cap, "distance_to_packing": new_dist}
            })
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": f"Failed to modify shelf: {str(exc)}"}), 500
    finally:
        conn.close()

@app.route("/api/warehouse/edges", methods=["POST", "DELETE"])
def manage_warehouse_edges():
    """Adds, updates, or deletes a corridor connection between two shelves."""
    data = request.get_json() or {}
    u = data.get("from_shelf_id")
    v = data.get("to_shelf_id")

    if u is None or v is None:
        return jsonify({"error": "'from_shelf_id' and 'to_shelf_id' are required."}), 400

    try:
        u, v = int(u), int(v)
    except (ValueError, TypeError):
        return jsonify({"error": "Shelf IDs must be integers."}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if request.method == "DELETE":
                cur.execute("DELETE FROM edges WHERE (from_shelf_id = %s AND to_shelf_id = %s) OR (from_shelf_id = %s AND to_shelf_id = %s)", (u, v, v, u))
                recalculate_warehouse_distances(conn)
                conn.commit()
                return jsonify({"status": "success", "message": f"Corridor between Shelf {u} and Shelf {v} deleted."})

            # POST: Add or update
            dist = float(data.get("distance", 6.0))
            cur.execute("DELETE FROM edges WHERE (from_shelf_id = %s AND to_shelf_id = %s) OR (from_shelf_id = %s AND to_shelf_id = %s)", (u, v, v, u))
            cur.execute("INSERT INTO edges (from_shelf_id, to_shelf_id, distance) VALUES (%s, %s, %s)", (u, v, dist))
            cur.execute("INSERT INTO edges (from_shelf_id, to_shelf_id, distance) VALUES (%s, %s, %s)", (v, u, dist))
            recalculate_warehouse_distances(conn)
            conn.commit()
            return jsonify({
                "status": "success",
                "message": f"Corridor between Shelf {u} and Shelf {v} set to {dist}m.",
                "edge": {"from_shelf_id": u, "to_shelf_id": v, "distance": dist}
            })
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": f"Failed to modify edge: {str(exc)}"}), 500
    finally:
        conn.close()

@app.route("/api/warehouse/corridor/block", methods=["POST"])
def block_warehouse_corridor():
    """
    Dynamically blocks a corridor (e.g. for spill/maintenance) or applies traffic penalty.
    Body: {"from_shelf": 2, "to_shelf": 3, "penalty": 40.0 (optional)}
    """
    data = request.get_json() or {}
    u = data.get("from_shelf")
    v = data.get("to_shelf")
    penalty = data.get("penalty")

    if u is None or v is None:
        return jsonify({"error": "'from_shelf' and 'to_shelf' IDs are required."}), 400

    try:
        u, v = int(u), int(v)
    except (ValueError, TypeError):
        return jsonify({"error": "'from_shelf' and 'to_shelf' must be integers."}), 400

    if penalty is not None:
        try:
            penalty = float(penalty)
        except (ValueError, TypeError):
            return jsonify({"error": "'penalty' must be a valid number."}), 400

    edge_key = (min(u, v), max(u, v))
    BLOCKED_CORRIDORS.add(edge_key)
    if penalty is not None:
        CORRIDOR_PENALTIES[edge_key] = penalty

    return jsonify({
        "status": "success",
        "message": f"Corridor between Shelf {u} and Shelf {v} has been blocked.",
        "blocked_corridor": {"from_shelf": u, "to_shelf": v, "penalty": penalty},
        "total_blocked": len(BLOCKED_CORRIDORS)
    })

@app.route("/api/warehouse/corridor/unblock", methods=["POST"])
def unblock_warehouse_corridor():
    """
    Restores normal traffic on a previously blocked corridor.
    Body: {"from_shelf": 2, "to_shelf": 3}
    """
    data = request.get_json() or {}
    u = data.get("from_shelf")
    v = data.get("to_shelf")

    if u is None or v is None:
        return jsonify({"error": "'from_shelf' and 'to_shelf' IDs are required."}), 400

    try:
        u, v = int(u), int(v)
    except (ValueError, TypeError):
        return jsonify({"error": "'from_shelf' and 'to_shelf' must be integers."}), 400

    edge_key = (min(u, v), max(u, v))
    BLOCKED_CORRIDORS.discard(edge_key)
    CORRIDOR_PENALTIES.pop(edge_key, None)

    return jsonify({
        "status": "success",
        "message": f"Corridor between Shelf {u} and Shelf {v} is now clear and walkable.",
        "unblocked_corridor": {"from_shelf": u, "to_shelf": v},
        "total_blocked": len(BLOCKED_CORRIDORS)
    })

@app.route("/api/warehouse/corridors/reset", methods=["POST"])
def reset_blocked_corridors():
    """Clears all dynamic corridor blocks and penalties."""
    BLOCKED_CORRIDORS.clear()
    CORRIDOR_PENALTIES.clear()
    return jsonify({
        "status": "success",
        "message": "All warehouse corridors reset to open status."
    })

@app.route("/api/warehouse/corridors/blocked", methods=["GET"])
def get_blocked_corridors_api():
    """Returns all currently blocked or penalized corridors."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        return jsonify({
            "blocked_corridors": warehouse.get_blocked_corridors(),
            "count": len(BLOCKED_CORRIDORS)
        })
    finally:
        conn.close()

def _get_request_user_email():
    """Helper to safely extract user email from Authorization header or default to admin."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        claims = verify_token(token)
        if claims and "sub" in claims:
            conn = get_db()
            try:
                user = fetch_user_by_id(conn, claims["sub"])
                if user:
                    return user.email
            finally:
                conn.close()
    return "admin@warehouse.io"

@app.route("/api/layout/optimize", methods=["GET", "POST"])
def optimize_layout():
    """
    Executes greedy layout optimization under chosen strategy (Velocity or COI).
    Returns proposed old vs new shelf assignments, travel index metrics, and floor heatmaps.
    """
    data = request.get_json(silent=True) or {}
    strategy = data.get("strategy") or request.args.get("strategy", "velocity")

    conn = get_db()
    try:
        products = fetch_all_products(conn)
        shelves = fetch_all_shelves(conn)
        optimizer = LayoutOptimizer()
        assignments, summary = optimizer.optimize(products, shelves, strategy=strategy)

        # Check if an undoable layout snapshot exists
        can_undo = False
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM layout_snapshots WHERE status = 'applied'")
            res = cur.fetchone()
            cnt = res["cnt"] if isinstance(res, dict) else res[0]
            can_undo = bool(cnt > 0)

        return jsonify({
            "status": "success",
            "strategy": strategy,
            "summary": summary,
            "assignments": assignments,
            "proposed_assignments": assignments,
            "can_undo": can_undo
        })
    finally:
        conn.close()

@app.route("/api/layout/apply", methods=["POST"])
@app.route("/api/layout/save", methods=["POST"])
def apply_layout():
    """
    Applies the proposed assignments to the database, writes a snapshot for undo,
    and records an audit trail entry.
    """
    data = request.get_json() or {}
    assignments = data.get("assignments")
    strategy = data.get("strategy", "velocity")
    summary = data.get("summary")
    user_email = _get_request_user_email()

    if assignments is not None and not isinstance(assignments, list):
        return jsonify({"error": "'assignments' must be a list of shelf mappings."}), 400

    conn = get_db()
    try:
        if not assignments:
            # If not supplied in request body, re-run optimizer and apply
            products = fetch_all_products(conn)
            shelves = fetch_all_shelves(conn)
            optimizer = LayoutOptimizer()
            assignments, summary = optimizer.optimize(products, shelves, strategy=strategy)

        optimizer = LayoutOptimizer()
        success, snapshot_id = optimizer.apply(
            conn, assignments, user_email=user_email, strategy=strategy, summary=summary
        )
        if not success:
            return jsonify({"status": "error", "error": snapshot_id}), 400

        return jsonify({
            "status": "success",
            "snapshot_id": snapshot_id,
            "updated_count": len(assignments),
            "message": f"Successfully updated shelf assignments for {len(assignments)} products."
        })
    finally:
        conn.close()

@app.route("/api/layout/undo", methods=["POST"])
def undo_layout():
    """
    Reverts the most recent applied layout snapshot, restoring original shelf assignments,
    and recording a warning audit entry.
    """
    user_email = _get_request_user_email()
    conn = get_db()
    try:
        optimizer = LayoutOptimizer()
        success, res = optimizer.undo(conn, user_email=user_email)
        if not success:
            return jsonify({"status": "error", "error": res}), 400

        return jsonify({
            "status": "success",
            "message": res["message"],
            "snapshot_id": res["snapshot_id"],
            "restored_count": res["restored_count"]
        })
    finally:
        conn.close()

@app.route("/api/layout/snapshot/latest", methods=["GET"])
def get_latest_layout_snapshot():
    """
    Returns metadata for the most recent active layout snapshot (for undo button state).
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, strategy, travel_index_before, travel_index_after, reduction_pct, user_email, status, created_at 
                FROM layout_snapshots 
                WHERE status = 'applied' 
                ORDER BY id DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                return jsonify({"has_snapshot": False, "snapshot": None})
            return jsonify({
                "has_snapshot": True,
                "snapshot": dict(row)
            })
    finally:
        conn.close()

@app.route("/api/orders/<int:order_id>/route", methods=["POST", "GET"])
def compute_order_route(order_id):
    """
    Computes the shortest picking route for the specified customer order.
    Uses Brute-Force (<8 stops) or Held-Karp (8-12 stops) for exact TSP, or 2-opt metaheuristics.
    """
    data = request.get_json(silent=True) or {}
    algorithm = data.get("algorithm") or request.args.get("algorithm", "auto")

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        orders = fetch_all_orders(conn)
        order = next((o for o in orders if o.id == order_id), None)
        if not order:
            return jsonify({"error": f"Order #{order_id} not found"}), 404

        shelf_ids = [item["shelf_id"] for item in order.items if item["shelf_id"] is not None]
        router = RouteOptimizer(warehouse)
        route_result = router.solve_order_route(order_id, shelf_ids, algorithm_choice=algorithm)
        route_result["customer_name"] = order.customer_name
        route_result["items"] = order.items
        route_result["status"] = order.status
        return jsonify(route_result)
    finally:
        conn.close()


@app.route("/api/orders/create", methods=["POST"])
def create_order():
    """
    Creates a new custom customer order with specified items and quantities.
    Saves to database and immediately returns optimal picking route.
    """
    data = request.get_json() or {}
    customer_name = data.get("customer_name", "").strip()
    items = data.get("items", [])

    if not customer_name:
        return jsonify({"error": "customer_name is required"}), 400
    if not items or not isinstance(items, list):
        return jsonify({"error": "items list is required and cannot be empty"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO orders (customer_name, status) VALUES (%s, %s)", (customer_name, "Pending"))
        order_id = cursor.lastrowid

        for it in items:
            if not isinstance(it, dict):
                return jsonify({"error": "Each item must be an object with product_id and quantity."}), 400
            p_id = it.get("product_id")
            if p_id is None:
                return jsonify({"error": "product_id is required for each item."}), 400
            try:
                p_id = int(p_id)
                qty = max(1, int(it.get("quantity", 1)))
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid product_id or quantity in items list."}), 400

            cursor.execute("INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)", (order_id, p_id, qty))

        conn.commit()

        cursor.execute("""
            SELECT p.id as product_id, p.name, p.category, p.assigned_shelf_id as shelf_id, oi.quantity
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
        """, (order_id,))
        order_items = cursor.fetchall()

        warehouse = fetch_warehouse(conn)
        shelf_ids = [row["shelf_id"] for row in order_items if row["shelf_id"] is not None]
        router = RouteOptimizer(warehouse)
        route_result = router.solve_order_route(order_id, shelf_ids)
        route_result["customer_name"] = customer_name
        route_result["items"] = order_items

        return jsonify({
            "status": "success",
            "message": f"Order #{order_id} created successfully.",
            "order_id": order_id,
            "route": route_result
        }), 201
    finally:
        cursor.close()
        conn.close()

@app.route("/api/orders/simulate", methods=["POST"])
def simulate_order():
    """
    Simulates a live incoming enterprise customer order with randomized items.
    Saves to MySQL and immediately returns optimal picking route.
    """
    import random
    company_prefixes = ["Apex", "Titan", "Quantum", "Nexus", "Vanguard", "Cyber", "Precision", "Global", "Nova", "Aero"]
    company_types = ["Robotics", "Systems", "Automation", "Fab", "Logistics", "Instruments", "Aerospace", "Manufacturing"]
    customer_name = f"{random.choice(company_prefixes)} {random.choice(company_types)} #{random.randint(100, 999)}"

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM products")
        all_product_ids = [row["id"] for row in cursor.fetchall()]

        num_items = random.randint(3, 8)
        selected_prods = random.sample(all_product_ids, min(num_items, len(all_product_ids)))

        cursor.execute("INSERT INTO orders (customer_name, status) VALUES (%s, %s)", (customer_name, "Pending"))
        order_id = cursor.lastrowid

        for p_id in selected_prods:
            qty = random.randint(1, 4)
            cursor.execute("INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)", (order_id, p_id, qty))

        conn.commit()

        cursor.execute("""
            SELECT p.id as product_id, p.name, p.category, p.assigned_shelf_id as shelf_id, oi.quantity
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
        """, (order_id,))
        order_items = cursor.fetchall()

        warehouse = fetch_warehouse(conn)
        shelf_ids = [row["shelf_id"] for row in order_items if row["shelf_id"] is not None]
        router = RouteOptimizer(warehouse)
        route_result = router.solve_order_route(order_id, shelf_ids)
        route_result["customer_name"] = customer_name
        route_result["items"] = order_items

        return jsonify({
            "status": "success",
            "message": f"Simulated Order #{order_id} generated for {customer_name}.",
            "order_id": order_id,
            "route": route_result
        }), 201
    finally:
        cursor.close()
        conn.close()

VALID_ORDER_STATUSES = {"Pending", "Picking", "Completed", "Cancelled"}

@app.route("/api/orders/<int:order_id>/status", methods=["PATCH", "PUT"])
def update_order_status(order_id):
    """
    Updates the operational lifecycle status of an order.
    Allowed statuses: 'Pending', 'Picking', 'Completed', 'Cancelled'.
    """
    data = request.get_json() or {}
    raw_status = data.get("status", "").strip()
    status_title = raw_status.title() if raw_status else ""
    if status_title not in VALID_ORDER_STATUSES:
        return jsonify({
            "error": f"Invalid status '{raw_status}'. Allowed statuses: {sorted(list(VALID_ORDER_STATUSES))}"
        }), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, customer_name, status FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                return jsonify({"error": f"Order #{order_id} not found"}), 404

            cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status_title, order_id))
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Order #{order_id} status updated from '{order['status']}' to '{status_title}'.",
            "order_id": order_id,
            "previous_status": order["status"],
            "new_status": status_title
        })
    finally:
        conn.close()

@app.route("/api/orders/<int:order_id>/complete", methods=["POST"])
def complete_order(order_id):
    """
    Marks an order as Completed and decrements physical inventory stock for all picked items.
    Logs each item deduction in inventory_transactions and verifies low-stock thresholds.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, customer_name, status FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                return jsonify({"error": f"Order #{order_id} not found"}), 404

            # Fetch line items to decrement stock
            cur.execute("""
                SELECT oi.product_id, oi.quantity, p.name, p.sku, p.stock_quantity, p.reorder_threshold
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s
            """, (order_id,))
            items = cur.fetchall()
            user_email = _get_request_user_email()

            for it in items:
                prev_q = it["stock_quantity"]
                new_q = max(0, prev_q - it["quantity"])
                cur.execute(
                    "UPDATE products SET stock_quantity = %s WHERE id = %s",
                    (new_q, it["product_id"])
                )
                record_inventory_movement(
                    conn, it["product_id"], "PICK", -it["quantity"], prev_q, new_q,
                    reason=f"Order #{order_id} fulfillment", ref_id=str(order_id), user_email=user_email
                )
                if new_q <= it["reorder_threshold"]:
                    create_notification(
                        conn, "LOW_STOCK",
                        f"Low Stock: {it['name']}",
                        f"Product '{it['name']}' ({it['sku']}) has {new_q} units remaining (threshold: {it['reorder_threshold']}).",
                        severity="warning"
                    )

            record_audit_log(
                conn, None, user_email, "ORDER_COMPLETE", "SUCCESS",
                f"Completed Order #{order_id} ({len(items)} items picked)"
            )
            cur.execute("UPDATE orders SET status = 'Completed' WHERE id = %s", (order_id,))
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Order #{order_id} marked as Completed. Inventory deducted for {len(items)} line items.",
            "order_id": order_id,
            "items_deducted": len(items),
            "new_status": "Completed"
        })
    finally:
        conn.close()

@app.route("/api/orders/<int:order_id>/dispatch", methods=["POST"])
def dispatch_order(order_id):
    """
    Assigns a warehouse picker and dispatches the order for active picking.
    Updates order status to 'Picking' and records an audit log.
    """
    data = request.get_json(silent=True) or {}
    picker = str(data.get("picker", "Picker Alpha")).strip()
    route_distance = float(data.get("route_distance", 0.0))

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, customer_name, status FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                return jsonify({"error": f"Order #{order_id} not found"}), 404

            cur.execute("UPDATE orders SET status = 'Picking' WHERE id = %s", (order_id,))
            
            user_email = _get_request_user_email()
            record_audit_log(
                conn, None, user_email, "ORDER_DISPATCH", "SUCCESS",
                f"Dispatched Order #{order_id} ({round(route_distance, 1)}m) to {picker}"
            )
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Order #{order_id} successfully dispatched to {picker} ({round(route_distance, 1)}m).",
            "order_id": order_id,
            "picker": picker,
            "new_status": "Picking"
        })
    finally:
        conn.close()


@app.route("/api/inventory/status", methods=["GET"])
def get_inventory_status():
    """
    Returns inventory health metrics including total stock, low-stock alerts,
    out-of-stock items, and inventory counts grouped by category.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, category, stock_quantity, assigned_shelf_id
                FROM products
                ORDER BY stock_quantity ASC
            """)
            prods = cur.fetchall()

            total_units = sum(p["stock_quantity"] for p in prods)
            low_stock = [p for p in prods if p["stock_quantity"] <= 15]
            out_of_stock = [p for p in prods if p["stock_quantity"] == 0]

            cat_summary = {}
            for p in prods:
                c = p["category"]
                cat_summary[c] = cat_summary.get(c, 0) + p["stock_quantity"]

        return jsonify({
            "total_products": len(prods),
            "total_units_in_stock": total_units,
            "low_stock_count": len(low_stock),
            "low_stock_items": low_stock[:10],
            "out_of_stock_count": len(out_of_stock),
            "stock_by_category": cat_summary
        })
    finally:
        conn.close()

@app.route("/api/inventory/restock", methods=["POST"])
def restock_inventory():
    """
    Replenishes product inventory stock.
    Supports single product restock: {"product_id": 5, "quantity": 25}
    Or bulk restock: {"restock_all_to": 50}
    Logs transactions in inventory_transactions.
    """
    data = request.get_json() or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if "restock_all_to" in data:
                try:
                    val = int(data["restock_all_to"])
                    if val <= 0:
                        return jsonify({"error": "'restock_all_to' must be greater than 0."}), 400
                except (ValueError, TypeError):
                    return jsonify({"error": "'restock_all_to' must be a valid integer."}), 400

                cur.execute("SELECT id, stock_quantity FROM products WHERE is_archived = 0")
                prods_to_restock = cur.fetchall()
                user_email = _get_request_user_email()
                for pr in prods_to_restock:
                    delta = val - pr["stock_quantity"]
                    if delta != 0:
                        record_inventory_movement(
                            conn, pr["id"], "RESTOCK", delta, pr["stock_quantity"], val,
                            reason="Bulk warehouse restock", user_email=user_email
                        )
                cur.execute("UPDATE products SET stock_quantity = %s WHERE is_archived = 0", (val,))
                conn.commit()
                return jsonify({
                    "status": "success",
                    "message": f"All warehouse products restocked to {val} units."
                })

            p_id = data.get("product_id")
            qty = data.get("quantity")
            if p_id is None or qty is None:
                return jsonify({"error": "Either 'product_id' and 'quantity', or 'restock_all_to' is required."}), 400

            try:
                p_id = int(p_id)
                qty = int(qty)
                if qty <= 0:
                    return jsonify({"error": "'quantity' must be a positive integer greater than 0."}), 400
            except (ValueError, TypeError):
                return jsonify({"error": "'product_id' and 'quantity' must be valid integers."}), 400

            cur.execute("SELECT id, name, sku, stock_quantity FROM products WHERE id = %s", (p_id,))
            prod = cur.fetchone()
            if not prod:
                return jsonify({"error": f"Product #{p_id} not found"}), 404

            prev_q = prod["stock_quantity"]
            new_q = prev_q + qty
            cur.execute("UPDATE products SET stock_quantity = %s WHERE id = %s", (new_q, p_id))
            user_email = _get_request_user_email()
            record_inventory_movement(
                conn, p_id, "RESTOCK", qty, prev_q, new_q,
                reason="Restock replenishment", user_email=user_email
            )
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Added {qty} units to '{prod['name']}'. New stock: {new_q}.",
            "product": {
                "id": p_id,
                "name": prod["name"],
                "sku": prod.get("sku", ""),
                "stock_quantity": new_q
            }
        })
    finally:
        conn.close()

@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    """
    Deletes an order and cascades line item removal.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, customer_name FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                return jsonify({"error": f"Order #{order_id} not found"}), 404

            cur.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
            cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Order #{order_id} for '{order['customer_name']}' deleted successfully.",
            "deleted_order_id": order_id
        })
    finally:
        conn.close()

@app.route("/api/orders/reset-simulated", methods=["POST", "DELETE"])
def reset_simulated_orders():
    """
    Removes dynamically simulated customer orders (ID > 12),
    preserving the initial 12 benchmark customer orders.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM orders WHERE id > 12")
            rows = cur.fetchall()
            simulated_ids = [r["id"] for r in rows]
            if simulated_ids:
                format_strings = ','.join(['%s'] * len(simulated_ids))
                cur.execute(f"DELETE FROM order_items WHERE order_id IN ({format_strings})", tuple(simulated_ids))
                cur.execute(f"DELETE FROM orders WHERE id IN ({format_strings})", tuple(simulated_ids))
                conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Purged {len(simulated_ids)} simulated orders. 12 benchmark orders preserved.",
            "deleted_count": len(simulated_ids)
        })
    finally:
        conn.close()

@app.route("/api/statistics", methods=["GET"])
def get_statistics():
    """
    Returns empirical before vs after distance comparisons across all orders,
    along with real database metrics for products, shelves, orders, and inventory.
    """
    time_slicer = request.args.get("time", "7d").lower()
    corridor = request.args.get("corr", "all").upper()
    engine = request.args.get("eng", "all").lower()

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
        stats["total_units"] = sum(p.stock_quantity for p in products)
        stats["total_valuation"] = round(sum(p.stock_quantity * p.unit_price for p in products), 2)
        stats["low_stock_count"] = sum(1 for p in products if p.is_low_stock)

        # Status breakdown
        st_counts = {"Pending": 0, "Picking": 0, "Completed": 0, "Cancelled": 0}
        for o in orders:
            s_name = (o.status or "Pending").title()
            st_counts[s_name] = st_counts.get(s_name, 0) + 1
        stats["order_status_counts"] = st_counts

        # SKU tier counts
        tier_counts = {"A": 0, "B": 0, "C": 0}
        sorted_prods = sorted(products, key=lambda x: x.pick_frequency, reverse=True)
        n = len(sorted_prods)
        for i, p in enumerate(sorted_prods):
            if i < int(n * 0.2):
                tier_counts["A"] += 1
            elif i < int(n * 0.5):
                tier_counts["B"] += 1
            else:
                tier_counts["C"] += 1
        stats["sku_tier_counts"] = tier_counts

        # Recent audit logs
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, action, status, details, created_at
                FROM auth_audit_logs
                ORDER BY id DESC LIMIT 6
            """)
            stats["recent_audit"] = cur.fetchall()

            # Active notifications
            cur.execute("""
                SELECT id, type, title, message, severity, created_at
                FROM notifications
                WHERE is_read = 0
                ORDER BY id DESC LIMIT 5
            """)
            stats["active_notifications"] = cur.fetchall()

        return jsonify(stats)
    finally:
        conn.close()

@app.route("/api/batch/waves", methods=["GET", "POST"])
def get_batch_waves():
    """
    Solves the Order Batching Problem (OBP). Groups all pending customer orders
    into wave picking batches to minimize aggregate walking distance.
    Supports optional cart_capacity parameter.
    """
    cart_capacity = parse_int_arg("cart_capacity", default=None)
    if cart_capacity is None:
        cart_capacity = parse_int_arg("max_cart_capacity", default=35, min_val=5, max_val=500)
    else:
        cart_capacity = max(5, min(500, cart_capacity))
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        orders = fetch_all_orders(conn)
        products = fetch_all_products(conn)
        shelf_mapping = {p.id: p.assigned_shelf_id for p in products}

        batcher = BatchOptimizer(warehouse, max_cart_capacity=cart_capacity)
        batches, metrics = batcher.optimize_batches(orders, shelf_mapping)

        return jsonify({
            "batches": batches,
            "metrics": metrics,
            "cart_capacity": cart_capacity
        })
    finally:
        conn.close()

@app.route("/api/fleet/assign", methods=["GET", "POST"])
def assign_fleet_workload():
    """
    Solves mTSP / CVRP fleet workload balancing.
    Distributes pending orders evenly across M warehouse pickers.
    """
    workers_count = parse_int_arg("workers", default=3, min_val=1, max_val=5)
    default_names = ["Picker Alpha", "Picker Bravo", "Picker Charlie", "Picker Delta", "Picker Echo"]
    names = default_names[:max(1, min(workers_count, len(default_names)))]

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        orders = fetch_all_orders(conn)
        products = fetch_all_products(conn)
        shelf_mapping = {p.id: p.assigned_shelf_id for p in products}

        allocator = FleetAllocator(warehouse, worker_names=names)
        worker_plans, metrics = allocator.allocate(orders, shelf_mapping)

        return jsonify({
            "workers": worker_plans,
            "metrics": metrics
        })
    finally:
        conn.close()

@app.route("/api/fleet/assign-waves", methods=["GET", "POST"])
def assign_fleet_waves():
    """
    Joint Operations Research Pipeline: Wave Batching + Fleet Allocation.
    1. Consolidates pending customer orders into optimal wave batches subject to cart capacity.
    2. Assigns waves across M pickers to minimize makespan and equalize shift workload.
    """
    workers_count = parse_int_arg("workers", default=3, min_val=1, max_val=5)
    cart_capacity = parse_int_arg("cart_capacity", default=None)
    if cart_capacity is None:
        cart_capacity = parse_int_arg("max_cart_capacity", default=35, min_val=5, max_val=500)
    else:
        cart_capacity = max(5, min(500, cart_capacity))
    default_names = ["Picker Alpha", "Picker Bravo", "Picker Charlie", "Picker Delta", "Picker Echo"]
    names = default_names[:max(1, min(workers_count, len(default_names)))]

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        orders = fetch_all_orders(conn)
        products = fetch_all_products(conn)
        shelf_mapping = {p.id: p.assigned_shelf_id for p in products}

        # Step 1: Solve Order Batching Problem (OBP)
        batcher = BatchOptimizer(warehouse, max_cart_capacity=cart_capacity)
        waves, wave_metrics = batcher.optimize_batches(orders, shelf_mapping)

        # Step 2: Solve mTSP Wave Allocation
        allocator = FleetAllocator(warehouse, worker_names=names)
        worker_plans, fleet_metrics = allocator.allocate_waves(waves)

        return jsonify({
            "status": "success",
            "workers": worker_plans,
            "fleet_metrics": fleet_metrics,
            "wave_metrics": wave_metrics,
            "cart_capacity": cart_capacity
        })
    finally:
        conn.close()

# -------------------------------------------------------------
# Fleet Balancing & Vehicle Management REST API Routes
# -------------------------------------------------------------

@app.route("/api/fleet/dashboard", methods=["GET"])
def get_fleet_dashboard():
    """
    Returns live executive Fleet Balancing dashboard metrics, warehouse distributions,
    active alerts, vehicles, and order assignments.
    """
    balancer = FleetBalancer()
    summary = balancer.get_dashboard_summary()
    vehicles = [v.to_dict() for v in balancer.fetch_vehicles()]
    orders = [o.to_dict() for o in balancer.fetch_orders(only_pending=False)]
    return jsonify({
        "status": "success",
        "metrics": summary["metrics"],
        "warehouse_summaries": summary["warehouse_summaries"],
        "imbalance_alerts": summary["imbalance_alerts"],
        "vehicles": vehicles,
        "orders": orders
    })

@app.route("/api/fleet/vehicles", methods=["GET"])
def get_fleet_vehicles():
    """
    Lists delivery fleet vehicles with optional search and filtering.
    """
    search = request.args.get("search", "").strip().lower()
    status_filter = request.args.get("status", "").strip()
    loc_filter = request.args.get("location", "").strip()
    type_filter = request.args.get("type", "").strip()

    balancer = FleetBalancer()
    vehicles = balancer.fetch_vehicles()

    filtered = []
    for v in vehicles:
        if status_filter and status_filter.lower() != "all" and v.status.lower() != status_filter.lower():
            continue
        if loc_filter and loc_filter.lower() != "all" and v.location.upper() != loc_filter.upper():
            continue
        if type_filter and type_filter.lower() != "all" and v.vehicle_type.lower() != type_filter.lower():
            continue
        if search:
            if search not in v.id.lower() and search not in v.name.lower() and search not in v.vehicle_type.lower():
                continue
        filtered.append(v.to_dict())

    return jsonify({"status": "success", "count": len(filtered), "vehicles": filtered})

@app.route("/api/fleet/vehicles", methods=["POST"])
def create_fleet_vehicle():
    """
    Creates a new vehicle with input validation.
    """
    data = request.get_json(silent=True) or {}
    veh_id = str(data.get("id", "")).strip().upper()
    name = str(data.get("name", "")).strip()
    v_type = str(data.get("vehicle_type", "Electric Van")).strip()
    raw_capacity = data.get("max_capacity")
    location = str(data.get("location", "WH-01")).strip().upper()
    status = str(data.get("status", "Available")).strip().title()
    cost_per_km = data.get("cost_per_km", 1.85)
    fixed_cost = data.get("fixed_cost", 25.0)

    # Validations
    if not veh_id:
        return jsonify({"status": "error", "message": "Vehicle ID is required."}), 400
    if not re.match(r'^[A-Z0-9_\-]+$', veh_id):
        return jsonify({"status": "error", "message": "Vehicle ID must contain only alphanumeric characters, underscores, and hyphens."}), 400
    if not name:
        return jsonify({"status": "error", "message": "Vehicle name is required."}), 400

    try:
        max_capacity = float(raw_capacity)
        if max_capacity <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Maximum capacity must be a positive number."}), 400

    try:
        cost_per_km = float(cost_per_km)
        fixed_cost = float(fixed_cost)
        if cost_per_km < 0 or fixed_cost < 0:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Operating costs must be non-negative numbers."}), 400

    if status not in ["Available", "In Transit", "Maintenance"]:
        return jsonify({"status": "error", "message": "Status must be 'Available', 'In Transit', or 'Maintenance'."}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Check for duplicate ID
            cur.execute("SELECT id FROM vehicles WHERE id = %s", (veh_id,))
            if cur.fetchone():
                return jsonify({"status": "error", "message": f"Vehicle ID '{veh_id}' already exists."}), 409

            # Verify warehouse exists
            cur.execute("SELECT id FROM warehouses WHERE id = %s", (location,))
            if not cur.fetchone():
                return jsonify({"status": "error", "message": f"Warehouse location '{location}' does not exist."}), 400

            cur.execute("""
                INSERT INTO vehicles (id, name, vehicle_type, max_capacity, current_load, location, status, cost_per_km, fixed_cost)
                VALUES (%s, %s, %s, %s, 0.0, %s, %s, %s, %s)
            """, (veh_id, name, v_type, max_capacity, location, status, cost_per_km, fixed_cost))
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Vehicle {veh_id} ({name}) created successfully.",
            "vehicle": {
                "id": veh_id,
                "name": name,
                "vehicle_type": v_type,
                "max_capacity": max_capacity,
                "current_load": 0.0,
                "location": location,
                "status": status,
                "cost_per_km": cost_per_km,
                "fixed_cost": fixed_cost
            }
        }), 201
    finally:
        conn.close()

@app.route("/api/fleet/vehicles/<vehicle_id>", methods=["GET"])
def get_fleet_vehicle_detail(vehicle_id):
    """
    Returns details of a specific vehicle including currently assigned orders.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, vehicle_type, max_capacity, current_load,
                       location, status, cost_per_km, fixed_cost, created_at
                FROM vehicles WHERE id = %s
            """, (vehicle_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": f"Vehicle '{vehicle_id}' not found."}), 404

            cur.execute("""
                SELECT id, customer_name, status, weight, destination_zone, priority, deadline, warehouse_id
                FROM orders WHERE assigned_vehicle_id = %s
                ORDER BY id ASC
            """, (vehicle_id,))
            orders_raw = cur.fetchall()

        v = Vehicle(
            id=row["id"],
            name=row["name"],
            vehicle_type=row["vehicle_type"],
            max_capacity=row["max_capacity"],
            current_load=row["current_load"],
            location=row["location"],
            status=row["status"],
            cost_per_km=row["cost_per_km"],
            fixed_cost=row["fixed_cost"],
            created_at=row.get("created_at")
        )
        res = v.to_dict()
        res["assigned_orders"] = orders_raw
        return jsonify({"status": "success", "vehicle": res})
    finally:
        conn.close()

@app.route("/api/fleet/vehicles/<vehicle_id>", methods=["PUT"])
def update_fleet_vehicle(vehicle_id):
    """
    Updates vehicle details with capacity and status validation.
    """
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM vehicles WHERE id = %s", (vehicle_id,))
            existing = cur.fetchone()
            if not existing:
                return jsonify({"status": "error", "message": f"Vehicle '{vehicle_id}' not found."}), 404

            name = data.get("name", existing["name"]).strip()
            v_type = data.get("vehicle_type", existing["vehicle_type"]).strip()
            raw_capacity = data.get("max_capacity", existing["max_capacity"])
            location = str(data.get("location", existing["location"])).strip().upper()
            status = str(data.get("status", existing["status"])).strip().title()
            cost_per_km = data.get("cost_per_km", existing["cost_per_km"])
            fixed_cost = data.get("fixed_cost", existing["fixed_cost"])

            try:
                max_capacity = float(raw_capacity)
                if max_capacity <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "Max capacity must be a positive number."}), 400

            if max_capacity < float(existing["current_load"]):
                return jsonify({
                    "status": "error",
                    "message": f"Cannot reduce capacity below currently assigned load ({existing['current_load']} kg)."
                }), 400

            if status not in ["Available", "In Transit", "Maintenance"]:
                return jsonify({"status": "error", "message": "Invalid status."}), 400

            cur.execute("""
                UPDATE vehicles
                SET name = %s, vehicle_type = %s, max_capacity = %s,
                    location = %s, status = %s, cost_per_km = %s, fixed_cost = %s
                WHERE id = %s
            """, (name, v_type, max_capacity, location, status, float(cost_per_km), float(fixed_cost), vehicle_id))
            conn.commit()

        return jsonify({"status": "success", "message": f"Vehicle '{vehicle_id}' updated successfully."})
    finally:
        conn.close()

@app.route("/api/fleet/vehicles/<vehicle_id>", methods=["DELETE"])
def delete_fleet_vehicle(vehicle_id):
    """
    Deletes a vehicle if no pending orders are currently assigned to it.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, current_load FROM vehicles WHERE id = %s", (vehicle_id,))
            veh = cur.fetchone()
            if not veh:
                return jsonify({"status": "error", "message": f"Vehicle '{vehicle_id}' not found."}), 404

            cur.execute("SELECT COUNT(*) as cnt FROM orders WHERE assigned_vehicle_id = %s AND status = 'Pending'", (vehicle_id,))
            cnt = cur.fetchone()["cnt"]
            if cnt > 0:
                return jsonify({
                    "status": "error",
                    "message": f"Cannot delete vehicle '{vehicle_id}' because it has {cnt} assigned pending orders. Please reassign or unassign first."
                }), 400

            cur.execute("DELETE FROM vehicle_assignments WHERE vehicle_id = %s", (vehicle_id,))
            cur.execute("DELETE FROM vehicles WHERE id = %s", (vehicle_id,))
            conn.commit()

        return jsonify({"status": "success", "message": f"Vehicle '{vehicle_id}' deleted successfully."})
    finally:
        conn.close()

@app.route("/api/fleet/orders", methods=["GET"])
def get_fleet_orders():
    """
    Lists orders with vehicle allocation information and filter capabilities.
    """
    status_filter = request.args.get("status", "").strip()
    assigned_filter = request.args.get("assigned", "").strip().lower()
    wh_filter = request.args.get("warehouse_id", "").strip().upper()
    priority_filter = request.args.get("priority", "").strip()
    search = request.args.get("search", "").strip().lower()

    conn = get_db()
    try:
        from backend.app import fetch_all_orders
        orders = fetch_all_orders(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT id, name, vehicle_type FROM vehicles")
            veh_map = {v["id"]: v for v in cur.fetchall()}

        filtered = []
        for o in orders:
            if status_filter and status_filter.lower() != "all" and o.status.lower() != status_filter.lower():
                continue
            if assigned_filter == "assigned" and not o.assigned_vehicle_id:
                continue
            if assigned_filter == "unassigned" and o.assigned_vehicle_id:
                continue
            if wh_filter and wh_filter != "ALL" and o.warehouse_id != wh_filter:
                continue
            if priority_filter and priority_filter.lower() != "all" and o.priority.lower() != priority_filter.lower():
                continue
            if search:
                if (search not in str(o.id).lower() and
                    search not in o.customer_name.lower() and
                    search not in o.destination_zone.lower()):
                    continue

            d = o.to_dict()
            if o.assigned_vehicle_id and o.assigned_vehicle_id in veh_map:
                d["vehicle_name"] = veh_map[o.assigned_vehicle_id]["name"]
                d["vehicle_type"] = veh_map[o.assigned_vehicle_id]["vehicle_type"]
            else:
                d["vehicle_name"] = None
                d["vehicle_type"] = None
            filtered.append(d)

        return jsonify({"status": "success", "count": len(filtered), "orders": filtered})
    finally:
        conn.close()

@app.route("/api/fleet/orders/<int:order_id>/assign", methods=["POST"])
def manually_assign_order(order_id):
    """
    Manually assigns a pending order to a vehicle with capacity validation.
    """
    data = request.get_json(silent=True) or {}
    vehicle_id = str(data.get("vehicle_id", "")).strip().upper()

    if not vehicle_id:
        return jsonify({"status": "error", "message": "vehicle_id is required."}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status, weight, assigned_vehicle_id FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                return jsonify({"status": "error", "message": f"Order #{order_id} not found."}), 404

            if order["status"] != "Pending":
                return jsonify({"status": "error", "message": f"Cannot assign order #{order_id} because status is '{order['status']}'."}), 400

            cur.execute("SELECT id, name, max_capacity, current_load, status FROM vehicles WHERE id = %s", (vehicle_id,))
            veh = cur.fetchone()
            if not veh:
                return jsonify({"status": "error", "message": f"Vehicle '{vehicle_id}' not found."}), 404

            if veh["status"] != "Available":
                return jsonify({"status": "error", "message": f"Vehicle '{vehicle_id}' is '{veh['status']}' and cannot accept assignments."}), 400

            order_weight = float(order.get("weight", 15.0))
            old_veh_id = order.get("assigned_vehicle_id")

            # Check capacity
            current_veh_load = float(veh["current_load"])
            if old_veh_id == vehicle_id:
                return jsonify({"status": "success", "message": f"Order #{order_id} is already assigned to {vehicle_id}."})

            if current_veh_load + order_weight > float(veh["max_capacity"]):
                return jsonify({
                    "status": "error",
                    "message": f"Capacity violation: {veh['name']} has {round(veh['max_capacity'] - current_veh_load, 1)} kg available, but order requires {order_weight} kg."
                }), 400

            # Decrement old vehicle load if it was assigned elsewhere
            if old_veh_id:
                cur.execute("UPDATE vehicles SET current_load = GREATEST(0, current_load - %s) WHERE id = %s", (order_weight, old_veh_id))

            # Assign to new vehicle
            cur.execute("UPDATE orders SET assigned_vehicle_id = %s WHERE id = %s", (vehicle_id, order_id))
            cur.execute("UPDATE vehicles SET current_load = current_load + %s WHERE id = %s", (order_weight, vehicle_id))
            cur.execute("INSERT INTO vehicle_assignments (vehicle_id, order_id, status) VALUES (%s, %s, 'Assigned')", (vehicle_id, order_id))
            conn.commit()

        return jsonify({
            "status": "success",
            "message": f"Order #{order_id} assigned to vehicle {vehicle_id} ({veh['name']})."
        })
    finally:
        conn.close()

@app.route("/api/fleet/orders/<int:order_id>/unassign", methods=["POST"])
def manually_unassign_order(order_id):
    """
    Unassigns an order from its current vehicle and updates capacity.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status, weight, assigned_vehicle_id FROM orders WHERE id = %s", (order_id,))
            order = cur.fetchone()
            if not order:
                return jsonify({"status": "error", "message": f"Order #{order_id} not found."}), 404

            veh_id = order.get("assigned_vehicle_id")
            if not veh_id:
                return jsonify({"status": "success", "message": f"Order #{order_id} is already unassigned."})

            weight = float(order.get("weight", 15.0))
            cur.execute("UPDATE orders SET assigned_vehicle_id = NULL WHERE id = %s", (order_id,))
            cur.execute("UPDATE vehicles SET current_load = GREATEST(0, current_load - %s) WHERE id = %s", (weight, veh_id))
            cur.execute("UPDATE vehicle_assignments SET status = 'Unassigned' WHERE order_id = %s", (order_id,))
            conn.commit()

        return jsonify({"status": "success", "message": f"Order #{order_id} unassigned successfully."})
    finally:
        conn.close()

@app.route("/api/fleet/warehouses", methods=["GET"])
def get_fleet_warehouses():
    """
    Returns warehouses with fleet capacity and pending order demand breakdown.
    """
    balancer = FleetBalancer()
    summary = balancer.get_dashboard_summary()
    return jsonify({
        "status": "success",
        "warehouses": summary["warehouse_summaries"]
    })

@app.route("/api/fleet/balance/run", methods=["POST"])
def run_fleet_balancing_action():
    """
    Runs the Fleet Balancing Optimization Algorithm.
    Generates proposed allocation, metrics, comparisons, and recommendations.
    Saves a 'Proposed' balancing run record in the database.
    """
    data = request.get_json(silent=True) or {}
    strategy = data.get("strategy", "best_fit_zone")

    balancer = FleetBalancer()
    result = balancer.run_balancing(strategy=strategy)

    return jsonify({
        "status": "success",
        "result": result
    })

@app.route("/api/fleet/balance/apply", methods=["POST"])
def apply_fleet_balancing_action():
    """
    Applies the proposed Fleet Balancing plan into the live database.
    Requires user confirmation and run_id.
    """
    data = request.get_json(silent=True) or {}
    run_id = data.get("run_id")

    if not run_id:
        return jsonify({"status": "error", "message": "run_id is required."}), 400

    try:
        balancer = FleetBalancer()
        result = balancer.apply_balancing(int(run_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/fleet/balance/discard", methods=["POST"])
def discard_fleet_balancing_action():
    """
    Discards a proposed Fleet Balancing run.
    """
    data = request.get_json(silent=True) or {}
    run_id = data.get("run_id")

    if not run_id:
        return jsonify({"status": "error", "message": "run_id is required."}), 400

    try:
        balancer = FleetBalancer()
        result = balancer.discard_balancing(int(run_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/fleet/balance/runs", methods=["GET"])
def get_fleet_balancing_runs():
    """
    Returns history of Fleet Balancing optimization executions.
    """
    limit = parse_int_arg("limit", default=20, min_val=1, max_val=100)
    balancer = FleetBalancer()
    runs = balancer.get_runs_history(limit=limit)
    return jsonify({
        "status": "success",
        "count": len(runs),
        "runs": runs
    })


# -------------------------------------------------------------
# Wave Picking REST API Endpoints
# -------------------------------------------------------------

@app.route("/api/waves/dashboard", methods=["GET"])
def get_waves_dashboard():
    """Returns live KPI metrics calculated from real database records."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        metrics = manager.get_dashboard_metrics()
        return jsonify({
            "status": "success",
            "metrics": metrics
        })
    finally:
        conn.close()

@app.route("/api/waves", methods=["GET"])
def get_waves_list():
    """Lists picking waves with search, status, priority, and picker filters."""
    status = request.args.get("status")
    priority = request.args.get("priority")
    picker = request.args.get("picker")
    search = request.args.get("search")

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        waves = manager.list_waves(status=status, priority=priority, picker=picker, search=search)
        return jsonify({
            "status": "success",
            "count": len(waves),
            "waves": waves
        })
    finally:
        conn.close()

@app.route("/api/waves/eligible-orders", methods=["GET"])
def get_eligible_wave_orders():
    """Returns all unallocated Pending customer orders ready to be formed into waves."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        orders = manager.get_eligible_orders()
        return jsonify({
            "status": "success",
            "count": len(orders),
            "orders": [o.to_dict() for o in orders]
        })
    finally:
        conn.close()

@app.route("/api/waves/preview", methods=["POST"])
def preview_wave_proposal():
    """
    Synthesizes wave proposals without persisting to database.
    Evaluates groupings, stock verification, and TSP travel savings.
    """
    body = request.get_json(silent=True) or {}
    strategy = body.get("strategy", "Hybrid")
    max_cart_capacity = parse_int_arg("max_cart_capacity", default=35, min_val=5, max_val=200)
    max_orders_per_batch = parse_int_arg("max_orders_per_batch", default=4, min_val=1, max_val=20)
    priority = body.get("priority", "Standard")
    assigned_picker = body.get("assigned_picker", "Alex Morgan")
    selected_order_ids = body.get("order_ids")

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)

        if selected_order_ids:
            all_orders = fetch_all_orders(conn)
            orders = [o for o in all_orders if o.id in selected_order_ids]
        else:
            orders = manager.get_eligible_orders()

        products = fetch_all_products(conn)
        shelf_mapping = {p.id: p.assigned_shelf_id for p in products}

        proposal = manager.generate_wave_proposal(
            orders=orders,
            strategy=strategy,
            max_cart_capacity=max_cart_capacity,
            max_orders_per_batch=max_orders_per_batch,
            priority=priority,
            assigned_picker=assigned_picker,
            shelf_mapping=shelf_mapping
        )
        return jsonify({
            "status": "success",
            "proposal": proposal
        })
    finally:
        conn.close()

@app.route("/api/waves", methods=["POST"])
def create_wave():
    """Creates and persists a new wave batch with consolidated pick tasks."""
    body = request.get_json(silent=True) or {}
    order_ids = body.get("order_ids")
    if not order_ids or not isinstance(order_ids, list):
        return jsonify({"status": "error", "message": "order_ids list is required"}), 400

    name = body.get("name")
    strategy = body.get("strategy", "Hybrid")
    priority = body.get("priority", "Standard")
    assigned_picker = body.get("assigned_picker", "Alex Morgan")
    max_cart_capacity = int(body.get("max_cart_capacity", 35))
    scheduled_at = body.get("scheduled_at")
    deadline = body.get("deadline")
    notes = body.get("notes")

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.create_wave(
            name=name,
            order_ids=order_ids,
            strategy=strategy,
            priority=priority,
            assigned_picker=assigned_picker,
            max_cart_capacity=max_cart_capacity,
            scheduled_at=scheduled_at,
            deadline=deadline,
            notes=notes
        )
        return jsonify({
            "status": "success",
            "message": f"Wave {wave['id']} successfully created.",
            "wave": wave
        }), 201
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>", methods=["GET"])
def get_wave_detail(wave_id):
    """Retrieves full details of a specific Wave by ID."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.get_wave(wave_id)
        if not wave:
            return jsonify({"status": "error", "message": f"Wave {wave_id} not found"}), 404
        return jsonify({
            "status": "success",
            "wave": wave
        })
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/start", methods=["POST"])
def start_wave(wave_id):
    """Starts a wave, verifies stock, builds reservations, and activates orders."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.start_wave(wave_id)
        return jsonify({
            "status": "success",
            "message": f"Wave {wave_id} is now Active.",
            "wave": wave
        })
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/pause", methods=["POST"])
def pause_wave(wave_id):
    """Pauses an active wave."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.pause_wave(wave_id)
        return jsonify({
            "status": "success",
            "message": f"Wave {wave_id} paused.",
            "wave": wave
        })
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/tasks/<int:task_id>/pick", methods=["POST"])
def pick_wave_task(wave_id, task_id):
    """Confirms picked quantity for an individual SKU-level pick task."""
    body = request.get_json(silent=True) or {}
    picked_quantity = body.get("picked_quantity")
    if picked_quantity is None:
        return jsonify({"status": "error", "message": "picked_quantity is required"}), 400

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.pick_task(wave_id, task_id, picked_quantity=picked_quantity)
        return jsonify({
            "status": "success",
            "message": f"Task {task_id} updated.",
            "wave": wave
        })
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/tasks/<int:task_id>/exception", methods=["POST"])
def report_wave_task_exception(wave_id, task_id):
    """Records an exception (shortage, damaged, blocked aisle) for a pick task."""
    body = request.get_json(silent=True) or {}
    exception_type = body.get("exception_type", "Shortage")
    details = body.get("details", "Stock shortage reported by picker.")

    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.report_task_exception(wave_id, task_id, exception_type=exception_type, details=details)
        return jsonify({
            "status": "success",
            "message": f"Exception recorded for task {task_id}.",
            "wave": wave
        })
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/complete", methods=["POST"])
def complete_wave(wave_id):
    """Completes wave, deducts inventory, fulfills reservations, marks orders Picked."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.complete_wave(wave_id)
        return jsonify({
            "status": "success",
            "message": f"Wave {wave_id} completed and inventory updated.",
            "wave": wave
        })
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/cancel", methods=["POST"])
def cancel_wave(wave_id):
    """Cancels wave, releases reservations, and restores orders to Pending."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        wave = manager.cancel_wave(wave_id)
        return jsonify({
            "status": "success",
            "message": f"Wave {wave_id} cancelled and reservations released.",
            "wave": wave
        })
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/waves/<wave_id>/export", methods=["GET"])
def export_wave_csv(wave_id):
    """Exports consolidated pick list as a CSV file download."""
    conn = get_db()
    try:
        warehouse = fetch_warehouse(conn)
        manager = WaveManager(conn, warehouse)
        csv_data = manager.export_wave_csv(wave_id)
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={wave_id}_pick_list.csv"}
        )
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    finally:
        conn.close()

# -------------------------------------------------------------
# Frontend Static Routing
# -------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "landing.html")

@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory(FRONTEND_DIR, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"Warehouse Optimizer Server running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
