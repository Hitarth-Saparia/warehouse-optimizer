"""
database/seed.py
Populates the MySQL database with realistic sample warehouse data:
- 25 Shelves (Shelf 1 = Packing Area, Shelves 2-25 in aisles)
- Graph Edges connecting aisles and packing station
- 60 Products across different categories (Fragile, Heavy, Electronics, etc.)
- 6 months of Sales records (used to calculate pick frequency)
- 12 Sample Customer Orders (varying from 2 to 9 items to test TSP vs Nearest-Neighbor)
"""

import os
import random
import pymysql

env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
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
    "autocommit": False
}

def get_connection(include_db=True):
    config = dict(DB_CONFIG)
    if not include_db:
        config.pop("database", None)
    return pymysql.connect(**config)

def run_schema(cursor):
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        sql = f.read()
    
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    for stmt in statements:
        cursor.execute(stmt)

def seed_database():
    # Connect without db first to ensure wareopt database is created
    init_conn = get_connection(include_db=False)
    init_cur = init_conn.cursor()
    init_cur.execute("CREATE DATABASE IF NOT EXISTS wareopt;")
    init_conn.commit()
    init_cur.close()
    init_conn.close()

    conn = get_connection(include_db=True)
    cursor = conn.cursor()
    print("Resetting database with schema.sql...")
    run_schema(cursor)
    conn.commit()

    print("Seeding shelves and coordinates...")
    # 25 shelves arranged in a clean warehouse grid
    # Shelf 1: Packing & Dispatch Area (x=80, y=260, dist=0)
    # Aisle 1 (x=220): Shelves 2, 3, 4, 5, 6, 7
    # Aisle 2 (x=380): Shelves 8, 9, 10, 11, 12, 13
    # Aisle 3 (x=540): Shelves 14, 15, 16, 17, 18, 19
    # Aisle 4 (x=700): Shelves 20, 21, 22, 23, 24, 25
    shelves_data = [
        # (id, distance_to_packing, capacity, current_load, x, y)
        (1, 0.0, 999, 0, 80, 260), # Packing Area
    ]
    
    y_coords = [80, 150, 220, 290, 360, 430]
    shelf_id = 2
    aisle_x = [220, 380, 540, 700]
    aisle_base_dist = [8.0, 16.0, 24.0, 32.0]

    for a_idx, x in enumerate(aisle_x):
        base_d = aisle_base_dist[a_idx]
        for row_idx, y in enumerate(y_coords):
            # Distance increases with aisle depth from the main corridor (y=260)
            dist = round(base_d + abs(y - 260) * 0.06 + row_idx * 1.5, 1)
            shelves_data.append((shelf_id, dist, 5, 0, x, y))
            shelf_id += 1

    cursor.executemany(
        "INSERT INTO shelves (id, distance_to_packing, capacity, current_load, x, y) VALUES (%s, %s, %s, %s, %s, %s)",
        shelves_data
    )

    print("Seeding warehouse graph edges...")
    edges = []
    
    # 1. Connect Packing Area (Shelf 1) to the entrance of each aisle
    # Aisle entrances near central crossway: Shelf 4, 5 (Aisle 1), Shelf 10, 11 (Aisle 2), etc.
    cursor.execute("SELECT id, x, y FROM shelves WHERE id > 1")
    shelf_map = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    shelf_map[1] = (80, 260)

    # Shelf 1 connects to aisle 1 middle corridor (Shelf 4, 5)
    edges.append((1, 4, 10.0))
    edges.append((1, 5, 10.0))
    edges.append((1, 2, 14.0))

    # 2. Intra-aisle edges (vertical along each aisle)
    for a in range(4):
        start_s = 2 + a * 6
        for i in range(5):
            u = start_s + i
            v = start_s + i + 1
            dist = 6.0
            edges.append((u, v, dist))

    # 3. Cross-aisle connections (horizontal cross-corridors at top, middle, bottom)
    # Top cross-corridor: Shelf 2, 8, 14, 20
    edges.append((2, 8, 12.0))
    edges.append((8, 14, 12.0))
    edges.append((14, 20, 12.0))

    # Mid cross-corridor: Shelf 5, 11, 17, 23
    edges.append((5, 11, 12.0))
    edges.append((11, 17, 12.0))
    edges.append((17, 23, 12.0))

    # Bottom cross-corridor: Shelf 7, 13, 19, 25
    edges.append((7, 13, 12.0))
    edges.append((13, 19, 12.0))
    edges.append((19, 25, 12.0))

    # Make edges bidirectional (undirected graph representation)
    full_edges = []
    for u, v, w in edges:
        full_edges.append((u, v, w))
        full_edges.append((v, u, w))

    cursor.executemany(
        "INSERT INTO edges (from_shelf_id, to_shelf_id, distance) VALUES (%s, %s, %s)",
        full_edges
    )

    print("Seeding 60 products across categories...")
    # Categories: Fragile, Heavy, Electronics, Tools, Fasteners
    product_templates = [
        # Heavy products (must not be mixed with fragile)
        ("Heavy Industrial Motor", "Heavy", 400),
        ("Cast Iron Engine Block", "Heavy", 350),
        ("Hydraulic Floor Jack", "Heavy", 280),
        ("Pneumatic Breaker 45lb", "Heavy", 190),
        ("Steel Beam Clamp 5-Ton", "Heavy", 150),
        ("Heavy Anvil 50kg", "Heavy", 120),
        ("Rotary Hammer Drill SDS", "Heavy", 310),
        ("Industrial Air Compressor", "Heavy", 260),
        ("Deep Cycle Lead Battery", "Heavy", 220),
        ("Welding Transformer 220V", "Heavy", 180),
        
        # Fragile products (must not be mixed with heavy)
        ("Laser Alignment Tube", "Fragile", 450),
        ("Precision Optical Sensor", "Fragile", 380),
        ("Laboratory Glass Flask", "Fragile", 320),
        ("Quartz Pressure Transducer", "Fragile", 290),
        ("Fiber Optic Spectrometer", "Fragile", 210),
        ("Ceramic Thermal Insulator", "Fragile", 160),
        ("Analog Galvanometer Glass", "Fragile", 110),
        ("Digital Caliper Optical Screen", "Fragile", 240),
        ("Vacuum Tube Glass Module", "Fragile", 95),
        ("Precision Camera Lens 50mm", "Fragile", 340),

        # Fast-moving Electronics (high sales velocity)
        ("Wireless Barcode Scanner", "Electronics", 520),
        ("Industrial Raspberry Pi 4", "Electronics", 490),
        ("Smart RFID Inventory Tag (50pk)", "Electronics", 650),
        ("Bluetooth Thermal Receipt Printer", "Electronics", 430),
        ("Handheld PDA Terminal", "Electronics", 390),
        ("Cat6 Shielded Patch Cable 10m", "Electronics", 580),
        ("Relay Controller Module 8-Ch", "Electronics", 360),
        ("DC Power Supply 24V 10A", "Electronics", 310),
        ("USB Inspection Endoscope", "Electronics", 270),
        ("Micro PLC CPU Unit", "Electronics", 230),

        # Power Tools & Workshop Equipment
        ("Cordless Brushless Impact Driver", "Tools", 480),
        ("Compact Angle Grinder 4.5in", "Tools", 410),
        ("Digital Torque Wrench 1/2in", "Tools", 350),
        ("Benchtop Drill Press", "Tools", 220),
        ("Reciprocating Saw 18V", "Tools", 330),
        ("Laser Distance Meter 100m", "Tools", 460),
        ("Socket Set Metric 120-pc", "Tools", 370),
        ("Pneumatic Rivet Gun", "Tools", 190),
        ("Heat Gun Variable Temp", "Tools", 280),
        ("Precision Soldering Station", "Tools", 310),

        # Fasteners & Hardware (High volume small picks)
        ("Hex Bolts M8 x 40mm (Pack 100)", "Fasteners", 620),
        ("Nylon Lock Nuts M6 (Pack 200)", "Fasteners", 590),
        ("Stainless Steel Washers M10", "Fasteners", 540),
        ("Socket Head Screws M5x20", "Fasteners", 510),
        ("Self-Drilling Metal Screws", "Fasteners", 470),
        ("Wall Anchor Assortment Kit", "Fasteners", 440),
        ("Heavy Duty Cable Ties 500mm", "Fasteners", 610),
        ("Spring Washers Grade 8.8", "Fasteners", 380),
        ("Brass Threaded Inserts M4", "Fasteners", 290),
        ("Expansion Anchors 12mm", "Fasteners", 210),

        # Safety & General Supplies
        ("Anti-Static Safety Gloves (Pair)", "Safety", 640),
        ("Auto-Darkening Welding Helmet", "Safety", 320),
        ("Kevlar Cut-Resistant Sleeves", "Safety", 280),
        ("Heavy Duty Safety Goggles", "Safety", 490),
        ("Chemical Spill Absorbent Pads", "Safety", 230),
        ("Reflective High-Vis Vest (L)", "Safety", 510),
        ("Ear Defenders 32dB NRR", "Safety", 390),
        ("Industrial First Aid Kit Class A", "Safety", 270),
        ("Particulate Respirator N95 Box", "Safety", 580),
        ("Steel Toe Safety Boots Size 10", "Safety", 340)
    ]

    # Assign initial random shelves (unoptimized layout for realistic baseline)
    # Storage shelves are 2 to 25 (Shelf 1 is packing)
    products_data = []
    available_shelves = list(range(2, 26))
    random.seed(42) # Deterministic for reproducible execution

    shelf_load_counter = {s: 0 for s in available_shelves}
    cat_prefix = {"Heavy": "HV", "Fragile": "FR", "Electronics": "EL", "Tools": "TL", "Fasteners": "FA", "Safety": "SF"}
    price_map = {"Heavy": 89.99, "Fragile": 129.50, "Electronics": 49.99, "Tools": 34.50, "Fasteners": 12.00, "Safety": 24.75}
    sku_counter = {}

    for name, cat, avg_units in product_templates:
        # Pick a random shelf that hasn't exceeded initial load limit
        valid_candidates = [s for s in available_shelves if shelf_load_counter[s] < 3]
        if not valid_candidates:
            valid_candidates = available_shelves
        assigned_shelf = random.choice(valid_candidates)
        shelf_load_counter[assigned_shelf] = shelf_load_counter.get(assigned_shelf, 0) + 1
        vol_map = {"Heavy": 3.5, "Fragile": 1.5, "Tools": 1.0, "Electronics": 0.5, "Fasteners": 0.1}
        vol = vol_map.get(cat, 1.0)
        p_idx = sku_counter.get(cat, 0) + 1
        sku_counter[cat] = p_idx
        sku = f"SKU-{cat_prefix.get(cat, 'GN')}-{p_idx:03d}"
        u_price = price_map.get(cat, 19.99)
        reorder_th = 15
        stock_qty = 50
        products_data.append((name, cat, assigned_shelf, stock_qty, vol, sku, reorder_th, u_price, 0))

    cursor.executemany(
        "INSERT INTO products (name, category, assigned_shelf_id, stock_quantity, volume, sku, reorder_threshold, unit_price, is_archived) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        products_data
    )

    # Update current_load on shelves
    for s_id, load in shelf_load_counter.items():
        cursor.execute("UPDATE shelves SET current_load = %s WHERE id = %s", (load, s_id))

    # Seed initial inbound inventory transactions
    cursor.execute("SELECT id, stock_quantity FROM products ORDER BY id ASC")
    seeded_prods = cursor.fetchall()
    inv_tx_data = [
        (p_row[0], "INBOUND", p_row[1], 0, p_row[1], "Initial warehouse stock receipt", "system@warehouse.io")
        for p_row in seeded_prods
    ]
    cursor.executemany(
        "INSERT INTO inventory_transactions (product_id, movement_type, quantity_change, previous_quantity, new_quantity, reason, user_email) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        inv_tx_data
    )

    # Seed initial operational notifications
    notifications_data = [
        ("SYSTEM", "Warehouse Engine Active", "Facility Digital Twin online with 24 storage shelves and Packing Dock S-01.", "success"),
        ("LOW_STOCK", "Reorder Threshold Policy Active", "Standard reorder threshold set to 15 units across all catalog items.", "info")
    ]
    cursor.executemany(
        "INSERT INTO notifications (type, title, message, severity) VALUES (%s, %s, %s, %s)",
        notifications_data
    )

    print("Seeding monthly sales records for pick frequency calculation...")
    # Fetch inserted product IDs
    cursor.execute("SELECT id, name FROM products ORDER BY id ASC")
    inserted_products = cursor.fetchall()

    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    sales_data = []

    for p_id, p_name in inserted_products:
        # Match template velocity
        base_velocity = next((item[2] for item in product_templates if item[0] == p_name), 200)
        for m in months:
            # Add small random variation per month (+/- 15%)
            variation = random.uniform(0.85, 1.15)
            monthly_units = max(5, int(base_velocity * variation))
            sales_data.append((p_id, m, monthly_units))

    cursor.executemany(
        "INSERT INTO sales (product_id, month, units_sold) VALUES (%s, %s, %s)",
        sales_data
    )

    print("Seeding warehouses and logistics hubs...")
    warehouses_data = [
        ("WH-01", "Central Distribution Center", "Downtown Logistics District", 0.0, 0.0, "Zone A - Downtown, Zone B - East Industrial"),
        ("WH-02", "North Metro Logistics Hub", "North Industrial Park", 15.0, 22.0, "Zone C - North Suburbs, Zone D - Airport Logistics"),
        ("WH-03", "West River Freight Depot", "West Port Corridor", -18.0, 10.0, "Zone E - West Harbor, Zone F - Tech Corridor")
    ]
    cursor.executemany(
        "INSERT INTO warehouses (id, name, location, coord_x, coord_y, service_zones) VALUES (%s, %s, %s, %s, %s, %s)",
        warehouses_data
    )

    print("Seeding vehicles fleet...")
    vehicles_data = [
        ("VEH-101", "EcoVan Alpha", "Electric Van", 650.0, 0.0, "WH-01", "Available", 1.25, 15.00),
        ("VEH-102", "Sprinter Beta", "Sprinter Van", 1200.0, 0.0, "WH-01", "Available", 1.75, 25.00),
        ("VEH-103", "BoxMaster 01", "Box Truck", 2500.0, 0.0, "WH-01", "Available", 2.60, 40.00),
        ("VEH-104", "Transporter Gamma", "Electric Van", 750.0, 0.0, "WH-02", "Available", 1.30, 18.00),
        ("VEH-105", "HeavyHaul 01", "Heavy Hauler", 4000.0, 0.0, "WH-02", "Available", 3.50, 60.00),
        ("VEH-106", "MetroVan Delta", "Cargo Van", 1000.0, 0.0, "WH-03", "Available", 1.65, 22.00),
        ("VEH-107", "Express Cruiser", "Sprinter Van", 1100.0, 0.0, "WH-03", "Maintenance", 1.80, 25.00),
        ("VEH-108", "City Runner 02", "Electric Van", 700.0, 0.0, "WH-03", "In Transit", 1.20, 16.00),
    ]
    cursor.executemany(
        "INSERT INTO vehicles (id, name, vehicle_type, max_capacity, current_load, location, status, cost_per_km, fixed_cost) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        vehicles_data
    )

    print("Seeding 12 sample orders (Orders 1-9 for TSP, Orders 10-12 for Nearest-Neighbor)...")
    customers = [
        ("Apex Logistics Hub", 140.0, "Zone A - Downtown", "Urgent", "14:00", "WH-01"),
        ("Starlight Manufacturing", 85.0, "Zone A - Downtown", "High", "16:00", "WH-01"),
        ("Apex Robotics Corp", 210.0, "Zone B - East Industrial", "Standard", "18:00", "WH-01"),
        ("Pinnacle Electronics Ltd", 95.0, "Zone B - East Industrial", "Standard", "18:00", "WH-01"),
        ("Vanguard Industrial Supplies", 320.0, "Zone A - Downtown", "High", "15:00", "WH-01"),
        ("Titan Dynamics Ltd", 175.0, "Zone C - North Suburbs", "Urgent", "13:30", "WH-02"),
        ("Metro Heavy Works", 480.0, "Zone D - Airport Logistics", "Standard", "18:00", "WH-02"),
        ("Orbital Precision Labs", 260.0, "Zone C - North Suburbs", "High", "16:30", "WH-02"),
        ("Horizon Automated Fab", 115.0, "Zone D - Airport Logistics", "Low", "Tomorrow 10:00", "WH-02"),
        ("Delta Mega Distribution", 520.0, "Zone E - West Harbor", "Standard", "17:00", "WH-03"),
        ("Pacific Engineering Group", 180.0, "Zone F - Tech Corridor", "High", "15:30", "WH-03"),
        ("Continental Assembly Corp", 290.0, "Zone E - West Harbor", "Urgent", "14:00", "WH-03")
    ]

    orders_data = [(i + 1, item[0], "Pending", item[1], item[2], item[3], item[4], item[5]) for i, item in enumerate(customers)]
    cursor.executemany(
        "INSERT INTO orders (id, customer_name, status, weight, destination_zone, priority, deadline, warehouse_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        orders_data
    )

    # Order Items:
    # Orders 1-9 have 2 to 5 distinct items (fewer than 8 stops -> triggers Brute-force TSP)
    # Orders 10-12 have 8 to 10 distinct items (triggers Nearest-Neighbor fallback)
    order_items_data = []
    prod_ids = [p[0] for p in inserted_products]

    for order_id in range(1, 13):
        if order_id <= 9:
            num_items = random.randint(3, 6) # < 8 items
        else:
            num_items = random.randint(8, 10) # >= 8 items for nearest-neighbor heuristic

        chosen_prods = random.sample(prod_ids, num_items)
        for p_id in chosen_prods:
            qty = random.randint(1, 4)
            order_items_data.append((order_id, p_id, qty))

    cursor.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)",
        order_items_data
    )

    print("Seeding initial administrative and operator user accounts...")
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from backend.security import hash_password

    demo_users = [
        ("admin@warehouse.io", "Alex Morgan", "password123", "manager"),
        ("supervisor@warehouse.io", "Elena Ramos", "password123", "supervisor"),
        ("fleet@warehouse.io", "David Chen", "password123", "fleet"),
        ("guest@warehouse.io", "Guest Analyst", "password123", "guest"),
    ]
    users_data = []
    for email, name, plain_pwd, role in demo_users:
        pwd_hash, salt = hash_password(plain_pwd)
        users_data.append((email, name, pwd_hash, salt, role))

    cursor.executemany(
        "INSERT INTO users (email, name, password_hash, salt, role) VALUES (%s, %s, %s, %s, %s)",
        users_data
    )

    conn.commit()
    cursor.close()
    conn.close()
    print("Database seeding completed successfully!")

if __name__ == "__main__":
    seed_database()
