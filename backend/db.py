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
    """)

    # Check if already seeded
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

    conn.commit()
    conn.close()
    print("[SQLite Fallback] Database initialized and seeded successfully.")


def get_sqlite_connection():
    """Returns a wrapped SQLite connection configured to match PyMySQL DictCursor."""
    if not os.path.exists(SQLITE_DB_PATH):
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
