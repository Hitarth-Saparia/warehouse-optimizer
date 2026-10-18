"""
backend/db.py
Database connection manager with seamless, resilient fallback to SQLite.
If MySQL is running and accessible on port 3306, the application utilizes MySQL.
If MySQL is stopped, not installed, or authentication fails, it automatically
falls back to a local SQLite database (database/wareopt.sqlite) with automatic schema
initialization and seeding, ensuring zero downtime and zero setup friction.
"""

import os
import re
import sqlite3
import random
import pymysql
import pymysql.cursors

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
SQLITE_DB_PATH = os.path.join(PROJECT_ROOT, "database", "wareopt.sqlite")

# Load environment configuration
env_file = os.path.join(PROJECT_ROOT, ".env")
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
    "autocommit": True,
    "connect_timeout": 2
}

ACTIVE_DB_TYPE = "mysql"  # "mysql" or "sqlite"


class SQLiteCursorWrapper:
    """Wraps an sqlite3.Cursor to emulate pymysql.cursors.DictCursor."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def _convert_sql(self, sql):
        # Convert %s placeholders to ?
        return re.sub(r'%s', '?', sql)

    def execute(self, sql, params=None):
        converted_sql = self._convert_sql(sql)
        if params is not None:
            if isinstance(params, list):
                params = tuple(params)
            return self._cursor.execute(converted_sql, params)
        return self._cursor.execute(converted_sql)

    def executemany(self, sql, seq_of_params):
        converted_sql = self._convert_sql(sql)
        return self._cursor.executemany(converted_sql, seq_of_params)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class SQLiteConnectionWrapper:
    """Wraps an sqlite3.Connection to emulate pymysql.Connection with DictCursor."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, cursorclass=None):
        raw_cur = self._conn.cursor()
        return SQLiteCursorWrapper(raw_cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()


def init_sqlite_database():
    """Initializes schema and seeds default data into the SQLite database."""
    os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cur = conn.cursor()

    # Create tables
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS shelves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            distance_to_packing REAL NOT NULL DEFAULT 0.0,
            capacity INTEGER NOT NULL DEFAULT 5,
            current_load INTEGER NOT NULL DEFAULT 0,
            x INTEGER NOT NULL DEFAULT 0,
            y INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            assigned_shelf_id INTEGER NULL,
            stock_quantity INTEGER NOT NULL DEFAULT 50,
            FOREIGN KEY (assigned_shelf_id) REFERENCES shelves(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            units_sold INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending'
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_shelf_id INTEGER NOT NULL,
            to_shelf_id INTEGER NOT NULL,
            distance REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'guest',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP NULL
        );

        CREATE TABLE IF NOT EXISTS auth_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NULL,
            email TEXT NOT NULL,
            action TEXT NOT NULL,
            ip_address TEXT NULL,
            status TEXT NOT NULL,
            details TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS warehouses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            coord_x REAL NOT NULL DEFAULT 0.0,
            coord_y REAL NOT NULL DEFAULT 0.0,
            service_zones TEXT NOT NULL DEFAULT 'Zone A, Zone B'
        );

        CREATE TABLE IF NOT EXISTS vehicles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            max_capacity REAL NOT NULL,
            current_load REAL NOT NULL DEFAULT 0.0,
            location TEXT NOT NULL DEFAULT 'WH-01',
            status TEXT NOT NULL DEFAULT 'Available',
            cost_per_km REAL NOT NULL DEFAULT 1.85,
            fixed_cost REAL NOT NULL DEFAULT 25.00,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (location) REFERENCES warehouses(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS vehicle_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id TEXT NOT NULL,
            order_id INTEGER NOT NULL,
            run_id INTEGER NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'Assigned',
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS balancing_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'Proposed',
            total_vehicles INTEGER NOT NULL DEFAULT 0,
            assigned_orders_count INTEGER NOT NULL DEFAULT 0,
            unassigned_orders_count INTEGER NOT NULL DEFAULT 0,
            fleet_utilization_pct REAL NOT NULL DEFAULT 0.0,
            cost_before REAL NOT NULL DEFAULT 0.0,
            cost_after REAL NOT NULL DEFAULT 0.0,
            cost_savings REAL NOT NULL DEFAULT 0.0,
            distance_before REAL NOT NULL DEFAULT 0.0,
            distance_after REAL NOT NULL DEFAULT 0.0,
            summary_json TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS waves (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Draft',
            strategy TEXT NOT NULL DEFAULT 'Hybrid',
            priority TEXT NOT NULL DEFAULT 'Standard',
            assigned_picker TEXT NULL,
            max_cart_capacity INTEGER NOT NULL DEFAULT 35,
            total_orders INTEGER NOT NULL DEFAULT 0,
            total_skus INTEGER NOT NULL DEFAULT 0,
            total_units INTEGER NOT NULL DEFAULT 0,
            picked_units INTEGER NOT NULL DEFAULT 0,
            estimated_distance_m REAL NOT NULL DEFAULT 0.0,
            unbatched_distance_m REAL NOT NULL DEFAULT 0.0,
            distance_saved_m REAL NOT NULL DEFAULT 0.0,
            scheduled_at TIMESTAMP NULL,
            deadline TIMESTAMP NULL,
            started_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL,
            notes TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS wave_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id TEXT NOT NULL,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Assigned',
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES waves(id) ON DELETE CASCADE,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pick_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            required_quantity INTEGER NOT NULL DEFAULT 1,
            picked_quantity INTEGER NOT NULL DEFAULT 0,
            shelf_id INTEGER NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            aisle_zone TEXT NULL,
            sequence_order INTEGER NOT NULL DEFAULT 0,
            exception_reason TEXT NULL,
            picked_at TIMESTAMP NULL,
            order_allocations TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES waves(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS inventory_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'Reserved',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES waves(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS wave_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id TEXT NOT NULL,
            task_id INTEGER NULL,
            product_id INTEGER NULL,
            exception_type TEXT NOT NULL,
            details TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES waves(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

    # Migrate orders table columns if missing
    cur.execute("PRAGMA table_info(orders)")
    existing_cols = {col[1] for col in cur.fetchall()}
    columns_to_add = [
        ("weight", "REAL NOT NULL DEFAULT 15.0"),
        ("destination_zone", "TEXT NOT NULL DEFAULT 'Zone A - Downtown'"),
        ("priority", "TEXT NOT NULL DEFAULT 'Standard'"),
        ("deadline", "TEXT NOT NULL DEFAULT '18:00'"),
        ("warehouse_id", "TEXT NOT NULL DEFAULT 'WH-01'"),
        ("assigned_vehicle_id", "TEXT NULL")
    ]
    for col_name, col_def in columns_to_add:
        if col_name not in existing_cols:
            cur.execute(f"ALTER TABLE orders ADD COLUMN {col_name} {col_def}")
    conn.commit()

    # Ensure demo user accounts are always seeded if missing
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        from backend.security import hash_password
        demo_users = [
            ("admin@warehouse.io", "Alex Morgan", "password123", "manager"),
            ("supervisor@warehouse.io", "Elena Ramos", "password123", "supervisor"),
            ("fleet@warehouse.io", "David Chen", "password123", "fleet"),
            ("guest@warehouse.io", "Guest Analyst", "password123", "guest"),
        ]
        sqlite_users_data = []
        for email, name, plain_pwd, role in demo_users:
            pwd_hash, salt = hash_password(plain_pwd)
            sqlite_users_data.append((email, name, pwd_hash, salt, role))

        cur.executemany(
            "INSERT INTO users (email, name, password_hash, salt, role) VALUES (?, ?, ?, ?, ?)",
            sqlite_users_data
        )
        conn.commit()

    # Seed Warehouses if empty
    cur.execute("SELECT COUNT(*) FROM warehouses")
    if cur.fetchone()[0] == 0:
        warehouses_seed = [
            ("WH-01", "Central Distribution Center", "Downtown Logistics District", 0.0, 0.0, "Zone A - Downtown, Zone B - East Industrial"),
            ("WH-02", "North Metro Logistics Hub", "North Industrial Park", 15.0, 22.0, "Zone C - North Suburbs, Zone D - Airport Logistics"),
            ("WH-03", "West River Freight Depot", "West Port Corridor", -18.0, 10.0, "Zone E - West Harbor, Zone F - Tech Corridor")
        ]
        cur.executemany(
            "INSERT INTO warehouses (id, name, location, coord_x, coord_y, service_zones) VALUES (?, ?, ?, ?, ?, ?)",
            warehouses_seed
        )
        conn.commit()

    # Seed Vehicles if empty
    cur.execute("SELECT COUNT(*) FROM vehicles")
    if cur.fetchone()[0] == 0:
        vehicles_seed = [
            ("VEH-101", "EcoVan Alpha", "Electric Van", 650.0, 0.0, "WH-01", "Available", 1.25, 15.00),
            ("VEH-102", "Sprinter Beta", "Sprinter Van", 1200.0, 0.0, "WH-01", "Available", 1.75, 25.00),
            ("VEH-103", "BoxMaster 01", "Box Truck", 2500.0, 0.0, "WH-01", "Available", 2.60, 40.00),
            ("VEH-104", "Transporter Gamma", "Electric Van", 750.0, 0.0, "WH-02", "Available", 1.30, 18.00),
            ("VEH-105", "HeavyHaul 01", "Heavy Hauler", 4000.0, 0.0, "WH-02", "Available", 3.50, 60.00),
            ("VEH-106", "MetroVan Delta", "Cargo Van", 1000.0, 0.0, "WH-03", "Available", 1.65, 22.00),
            ("VEH-107", "Express Cruiser", "Sprinter Van", 1100.0, 0.0, "WH-03", "Maintenance", 1.80, 25.00),
            ("VEH-108", "City Runner 02", "Electric Van", 700.0, 0.0, "WH-03", "In Transit", 1.20, 16.00),
        ]
        cur.executemany(
            "INSERT INTO vehicles (id, name, vehicle_type, max_capacity, current_load, location, status, cost_per_km, fixed_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            vehicles_seed
        )
        conn.commit()

    # Backfill or update sample orders 1 to 12 if they have default values
    cur.execute("SELECT id, weight, warehouse_id FROM orders WHERE id <= 12")
    existing_orders = cur.fetchall()
    if existing_orders:
        orders_meta = [
            (1, 140.0, "Zone A - Downtown", "Urgent", "14:00", "WH-01"),
            (2, 85.0, "Zone A - Downtown", "High", "16:00", "WH-01"),
            (3, 210.0, "Zone B - East Industrial", "Standard", "18:00", "WH-01"),
            (4, 95.0, "Zone B - East Industrial", "Standard", "18:00", "WH-01"),
            (5, 320.0, "Zone A - Downtown", "High", "15:00", "WH-01"),
            (6, 175.0, "Zone C - North Suburbs", "Urgent", "13:30", "WH-02"),
            (7, 480.0, "Zone D - Airport Logistics", "Standard", "18:00", "WH-02"),
            (8, 260.0, "Zone C - North Suburbs", "High", "16:30", "WH-02"),
            (9, 115.0, "Zone D - Airport Logistics", "Low", "Tomorrow 10:00", "WH-02"),
            (10, 520.0, "Zone E - West Harbor", "Standard", "17:00", "WH-03"),
            (11, 180.0, "Zone F - Tech Corridor", "High", "15:30", "WH-03"),
            (12, 290.0, "Zone E - West Harbor", "Urgent", "14:00", "WH-03"),
        ]
        # Only update if they appear un-migrated (e.g. weight == 15.0 for all)
        cur.execute("SELECT COUNT(DISTINCT weight) FROM orders WHERE id <= 12")
        distinct_weights = cur.fetchone()[0]
        if distinct_weights <= 1:
            for o_id, wt, zone, prio, dl, wh in orders_meta:
                cur.execute(
                    "UPDATE orders SET weight = ?, destination_zone = ?, priority = ?, deadline = ?, warehouse_id = ? WHERE id = ?",
                    (wt, zone, prio, dl, wh, o_id)
                )
            conn.commit()

    # Check if warehouse topology is already seeded
    cur.execute("SELECT COUNT(*) FROM shelves")
    if cur.fetchone()[0] > 0:
        conn.close()
        return

    print(f"[SQLite Fallback] Seeding initial warehouse topology into {SQLITE_DB_PATH}...")

    # Seed 25 Shelves
    shelves_data = [(1, 0.0, 999, 0, 80, 260)]
    y_coords = [80, 150, 220, 290, 360, 430]
    shelf_id = 2
    aisle_x = [220, 380, 540, 700]
    aisle_base_dist = [8.0, 16.0, 24.0, 32.0]

    for a_idx, x in enumerate(aisle_x):
        base_d = aisle_base_dist[a_idx]
        for row_idx, y in enumerate(y_coords):
            dist = round(base_d + abs(y - 260) * 0.06 + row_idx * 1.5, 1)
            shelves_data.append((shelf_id, dist, 5, 0, x, y))
            shelf_id += 1

    cur.executemany(
        "INSERT INTO shelves (id, distance_to_packing, capacity, current_load, x, y) VALUES (?, ?, ?, ?, ?, ?)",
        shelves_data
    )

    # Seed Edges
    edges = [
        (1, 4, 10.0), (1, 5, 10.0), (1, 2, 14.0),
        (2, 8, 12.0), (8, 14, 12.0), (14, 20, 12.0),
        (5, 11, 12.0), (11, 17, 12.0), (17, 23, 12.0),
        (7, 13, 12.0), (13, 19, 12.0), (19, 25, 12.0)
    ]
    for a in range(4):
        start_s = 2 + a * 6
        for i in range(5):
            edges.append((start_s + i, start_s + i + 1, 6.0))

    full_edges = []
    for u, v, w in edges:
        full_edges.append((u, v, w))
        full_edges.append((v, u, w))

    cur.executemany("INSERT INTO edges (from_shelf_id, to_shelf_id, distance) VALUES (?, ?, ?)", full_edges)

    # Seed Products
    product_templates = [
        ("Heavy Industrial Motor", "Heavy", 400), ("Cast Iron Engine Block", "Heavy", 350),
        ("Hydraulic Floor Jack", "Heavy", 280), ("Pneumatic Breaker 45lb", "Heavy", 190),
        ("Steel Beam Clamp 5-Ton", "Heavy", 150), ("Heavy Anvil 50kg", "Heavy", 120),
        ("Rotary Hammer Drill SDS", "Heavy", 310), ("Industrial Air Compressor", "Heavy", 260),
        ("Deep Cycle Lead Battery", "Heavy", 220), ("Welding Transformer 220V", "Heavy", 180),
        ("Laser Alignment Tube", "Fragile", 450), ("Precision Optical Sensor", "Fragile", 380),
        ("Laboratory Glass Flask", "Fragile", 320), ("Quartz Pressure Transducer", "Fragile", 290),
        ("Fiber Optic Spectrometer", "Fragile", 210), ("Ceramic Thermal Insulator", "Fragile", 160),
        ("Analog Galvanometer Glass", "Fragile", 110), ("Digital Caliper Optical Screen", "Fragile", 240),
        ("Vacuum Tube Glass Module", "Fragile", 95), ("Precision Camera Lens 50mm", "Fragile", 340),
        ("Wireless Barcode Scanner", "Electronics", 520), ("Industrial Raspberry Pi 4", "Electronics", 490),
        ("Smart RFID Inventory Tag (50pk)", "Electronics", 650), ("Bluetooth Thermal Receipt Printer", "Electronics", 430),
        ("Handheld PDA Terminal", "Electronics", 390), ("Cat6 Shielded Patch Cable 10m", "Electronics", 580),
        ("Relay Controller Module 8-Ch", "Electronics", 360), ("DC Power Supply 24V 10A", "Electronics", 310),
        ("USB Inspection Endoscope", "Electronics", 270), ("Micro PLC CPU Unit", "Electronics", 230),
        ("Cordless Brushless Impact Driver", "Tools", 480), ("Compact Angle Grinder 4.5in", "Tools", 410),
        ("Digital Torque Wrench 1/2in", "Tools", 350), ("Benchtop Drill Press", "Tools", 220),
        ("Reciprocating Saw 18V", "Tools", 330), ("Laser Distance Meter 100m", "Tools", 460),
        ("Socket Set Metric 120-pc", "Tools", 370), ("Pneumatic Rivet Gun", "Tools", 190),
        ("Heat Gun Variable Temp", "Tools", 280), ("Precision Soldering Station", "Tools", 310),
        ("Hex Bolts M8 x 40mm (Pack 100)", "Fasteners", 620), ("Nylon Lock Nuts M6 (Pack 200)", "Fasteners", 590),
        ("Stainless Steel Washers M10", "Fasteners", 540), ("Socket Head Screws M5x20", "Fasteners", 510),
        ("Self-Drilling Metal Screws", "Fasteners", 470), ("Wall Anchor Assortment Kit", "Fasteners", 440),
        ("Heavy Duty Cable Ties 500mm", "Fasteners", 610), ("Spring Washers Grade 8.8", "Fasteners", 380),
        ("Brass Threaded Inserts M4", "Fasteners", 290), ("Expansion Anchors 12mm", "Fasteners", 210),
        ("Anti-Static Safety Gloves (Pair)", "Safety", 640), ("Auto-Darkening Welding Helmet", "Safety", 320),
        ("Kevlar Cut-Resistant Sleeves", "Safety", 280), ("Heavy Duty Safety Goggles", "Safety", 490),
        ("Chemical Spill Absorbent Pads", "Safety", 230), ("Reflective High-Vis Vest (L)", "Safety", 510),
        ("Ear Defenders 32dB NRR", "Safety", 390), ("Industrial First Aid Kit Class A", "Safety", 270),
        ("Particulate Respirator N95 Box", "Safety", 580), ("Steel Toe Safety Boots Size 10", "Safety", 340)
    ]

    random.seed(42)
    available_shelves = list(range(2, 26))
    shelf_load_counter = {s: 0 for s in available_shelves}
    products_data = []

    for name, cat, _ in product_templates:
        candidates = [s for s in available_shelves if shelf_load_counter[s] < 3]
        s_choice = random.choice(candidates if candidates else available_shelves)
        shelf_load_counter[s_choice] = shelf_load_counter.get(s_choice, 0) + 1
        products_data.append((name, cat, s_choice, 50))

    cur.executemany("INSERT INTO products (name, category, assigned_shelf_id, stock_quantity) VALUES (?, ?, ?, ?)", products_data)

    for s_id, load in shelf_load_counter.items():
        cur.execute("UPDATE shelves SET current_load = ? WHERE id = ?", (load, s_id))

    # Sales
    cur.execute("SELECT id, name FROM products ORDER BY id ASC")
    inserted_products = cur.fetchall()
    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    sales_data = []
    for p_id, p_name in inserted_products:
        base_v = next((item[2] for item in product_templates if item[0] == p_name), 200)
        for m in months:
            sales_data.append((p_id, m, max(5, int(base_v * random.uniform(0.85, 1.15)))))

    cur.executemany("INSERT INTO sales (product_id, month, units_sold) VALUES (?, ?, ?)", sales_data)

    # Orders
    customers = [
        "Apex Logistics Hub", "Starlight Manufacturing", "Apex Robotics Corp",
        "Pinnacle Electronics Ltd", "Vanguard Industrial Supplies", "Titan Dynamics Ltd",
        "Metro Heavy Works", "Orbital Precision Labs", "Horizon Automated Fab",
        "Delta Mega Distribution", "Pacific Engineering Group", "Continental Assembly Corp"
    ]
    cur.executemany("INSERT INTO orders (id, customer_name, status) VALUES (?, ?, 'Pending')", [(i + 1, c) for i, c in enumerate(customers)])

    order_items_data = []
    prod_ids = [p[0] for p in inserted_products]
    for order_id in range(1, 13):
        k = random.randint(3, 6) if order_id <= 9 else random.randint(8, 10)
        for p_id in random.sample(prod_ids, k):
            order_items_data.append((order_id, p_id, random.randint(1, 4)))

    cur.executemany("INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)", order_items_data)

    # Seed Demo Users (if not already seeded)
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        from backend.security import hash_password
        demo_users = [
            ("admin@warehouse.io", "Alex Morgan", "password123", "manager"),
            ("supervisor@warehouse.io", "Elena Ramos", "password123", "supervisor"),
            ("fleet@warehouse.io", "David Chen", "password123", "fleet"),
            ("guest@warehouse.io", "Guest Analyst", "password123", "guest"),
        ]
        sqlite_users_data = []
        for email, name, plain_pwd, role in demo_users:
            pwd_hash, salt = hash_password(plain_pwd)
            sqlite_users_data.append((email, name, pwd_hash, salt, role))

        cur.executemany(
            "INSERT OR IGNORE INTO users (email, name, password_hash, salt, role) VALUES (?, ?, ?, ?, ?)",
            sqlite_users_data
        )

    conn.commit()
    conn.close()
    print("[SQLite Fallback] Database initialized and seeded successfully.")


def get_sqlite_connection():
    """Returns a wrapped SQLite connection configured to match PyMySQL DictCursor."""
    init_sqlite_database()

    raw_conn = sqlite3.connect(SQLITE_DB_PATH)
    raw_conn.row_factory = sqlite3.Row
    # Register GREATEST function for compatibility
    raw_conn.create_function("GREATEST", -1, max)
    return SQLiteConnectionWrapper(raw_conn)


def get_db():
    """
    Primary database accessor.
    Attempts connection to MySQL. If MySQL is unreachable, seamlessly returns SQLite connection.
    """
    global ACTIVE_DB_TYPE
    # Attempt MySQL first if not forcefully disabled
    if os.environ.get("USE_SQLITE", "").lower() not in ("1", "true"):
        try:
            conn = pymysql.connect(**DB_CONFIG)
            ACTIVE_DB_TYPE = "mysql"
            return conn
        except (pymysql.err.OperationalError, pymysql.err.InternalError, pymysql.err.ProgrammingError) as err:
            if ACTIVE_DB_TYPE != "sqlite":
                print(f"[DB Warning] Could not connect to MySQL ({err}). Seamlessly switching to SQLite fallback.")
            ACTIVE_DB_TYPE = "sqlite"
    else:
        ACTIVE_DB_TYPE = "sqlite"

    return get_sqlite_connection()


def get_active_db_type():
    """Returns the currently active database backend ('mysql' or 'sqlite')."""
    return ACTIVE_DB_TYPE
