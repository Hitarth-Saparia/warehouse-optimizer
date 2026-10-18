-- Warehouse Layout & Order Picking Optimizer
-- Database Schema for MySQL

CREATE DATABASE IF NOT EXISTS wareopt;
USE wareopt;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS balancing_runs;
DROP TABLE IF EXISTS vehicle_assignments;
DROP TABLE IF EXISTS vehicles;
DROP TABLE IF EXISTS warehouses;
DROP TABLE IF EXISTS auth_audit_logs;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS edges;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS shelves;
SET FOREIGN_KEY_CHECKS = 1;

-- 1. Shelves table: physical storage locations in the warehouse
-- Shelf 1 represents the Packing & Dispatch Area (distance_to_packing = 0)
CREATE TABLE shelves (
    id INT AUTO_INCREMENT PRIMARY KEY,
    distance_to_packing FLOAT NOT NULL DEFAULT 0.0,
    capacity INT NOT NULL DEFAULT 5,
    current_load INT NOT NULL DEFAULT 0,
    x INT NOT NULL DEFAULT 0,
    y INT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

-- 2. Products table: catalog items assigned to shelves
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    category VARCHAR(80) NOT NULL,
    assigned_shelf_id INT NULL,
    stock_quantity INT NOT NULL DEFAULT 50,
    volume FLOAT NOT NULL DEFAULT 1.0,
    CONSTRAINT fk_prod_shelf FOREIGN KEY (assigned_shelf_id) 
        REFERENCES shelves(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 3. Sales table: monthly sales records used to calculate pick frequency
CREATE TABLE sales (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    month VARCHAR(20) NOT NULL,
    units_sold INT NOT NULL DEFAULT 0,
    CONSTRAINT fk_sales_prod FOREIGN KEY (product_id) 
        REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 4. Orders table: customer orders to be picked and dispatched
CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(150) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    weight FLOAT NOT NULL DEFAULT 15.0,
    destination_zone VARCHAR(100) NOT NULL DEFAULT 'Zone A - Downtown',
    priority VARCHAR(50) NOT NULL DEFAULT 'Standard',
    deadline VARCHAR(50) NOT NULL DEFAULT '18:00',
    warehouse_id VARCHAR(50) NOT NULL DEFAULT 'WH-01',
    assigned_vehicle_id VARCHAR(50) NULL
) ENGINE=InnoDB;

-- 5. Order items: line items in each customer order
CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    CONSTRAINT fk_item_order FOREIGN KEY (order_id) 
        REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_item_prod FOREIGN KEY (product_id) 
        REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 6. Edges table: aisle connectivity and distances between shelves (graph model)
CREATE TABLE edges (
    id INT AUTO_INCREMENT PRIMARY KEY,
    from_shelf_id INT NOT NULL,
    to_shelf_id INT NOT NULL,
    distance FLOAT NOT NULL,
    CONSTRAINT fk_edge_from FOREIGN KEY (from_shelf_id) 
        REFERENCES shelves(id) ON DELETE CASCADE,
    CONSTRAINT fk_edge_to FOREIGN KEY (to_shelf_id) 
        REFERENCES shelves(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 7. Users table: system users with salted PBKDF2 password hashes and RBAC roles
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(120) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    salt VARCHAR(64) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'guest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
) ENGINE=InnoDB;

-- 8. Auth Audit Logs table: security audit trail tracking authentication events
CREATE TABLE auth_audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    email VARCHAR(120) NOT NULL,
    action VARCHAR(50) NOT NULL,
    ip_address VARCHAR(45) NULL,
    status VARCHAR(20) NOT NULL,
    details VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 9. Warehouses table: regional distribution and fulfillment hubs
CREATE TABLE warehouses (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    location VARCHAR(150) NOT NULL,
    coord_x FLOAT NOT NULL DEFAULT 0.0,
    coord_y FLOAT NOT NULL DEFAULT 0.0,
    service_zones VARCHAR(255) NOT NULL DEFAULT 'Zone A, Zone B'
) ENGINE=InnoDB;

-- 10. Vehicles table: fleet delivery vehicles
CREATE TABLE vehicles (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    vehicle_type VARCHAR(50) NOT NULL,
    max_capacity FLOAT NOT NULL,
    current_load FLOAT NOT NULL DEFAULT 0.0,
    location VARCHAR(50) NOT NULL DEFAULT 'WH-01',
    status VARCHAR(50) NOT NULL DEFAULT 'Available',
    cost_per_km FLOAT NOT NULL DEFAULT 1.85,
    fixed_cost FLOAT NOT NULL DEFAULT 25.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_veh_warehouse FOREIGN KEY (location) 
        REFERENCES warehouses(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- 11. Vehicle Assignments table: persistent record of order allocations to vehicles
CREATE TABLE vehicle_assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    vehicle_id VARCHAR(50) NOT NULL,
    order_id INT NOT NULL,
    run_id INT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) NOT NULL DEFAULT 'Assigned',
    CONSTRAINT fk_asgn_veh FOREIGN KEY (vehicle_id) 
        REFERENCES vehicles(id) ON DELETE CASCADE,
    CONSTRAINT fk_asgn_order FOREIGN KEY (order_id) 
        REFERENCES orders(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 12. Balancing Runs table: history of Fleet Balancing optimization executions
CREATE TABLE balancing_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    status VARCHAR(50) NOT NULL DEFAULT 'Proposed',
    total_vehicles INT NOT NULL DEFAULT 0,
    assigned_orders_count INT NOT NULL DEFAULT 0,
    unassigned_orders_count INT NOT NULL DEFAULT 0,
    fleet_utilization_pct FLOAT NOT NULL DEFAULT 0.0,
    cost_before FLOAT NOT NULL DEFAULT 0.0,
    cost_after FLOAT NOT NULL DEFAULT 0.0,
    cost_savings FLOAT NOT NULL DEFAULT 0.0,
    distance_before FLOAT NOT NULL DEFAULT 0.0,
    distance_after FLOAT NOT NULL DEFAULT 0.0,
    summary_json TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 13. Waves table: consolidated order picking batches
CREATE TABLE waves (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Draft',
    strategy VARCHAR(50) NOT NULL DEFAULT 'Hybrid',
    priority VARCHAR(50) NOT NULL DEFAULT 'Standard',
    assigned_picker VARCHAR(100) NULL,
    max_cart_capacity INT NOT NULL DEFAULT 35,
    total_orders INT NOT NULL DEFAULT 0,
    total_skus INT NOT NULL DEFAULT 0,
    total_units INT NOT NULL DEFAULT 0,
    picked_units INT NOT NULL DEFAULT 0,
    estimated_distance_m FLOAT NOT NULL DEFAULT 0.0,
    unbatched_distance_m FLOAT NOT NULL DEFAULT 0.0,
    distance_saved_m FLOAT NOT NULL DEFAULT 0.0,
    scheduled_at TIMESTAMP NULL,
    deadline TIMESTAMP NULL,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    notes TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 14. Wave Orders table: association between picking waves and orders
CREATE TABLE wave_orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wave_id VARCHAR(50) NOT NULL,
    order_id INT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Assigned',
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_wave_order_wave FOREIGN KEY (wave_id)
        REFERENCES waves(id) ON DELETE CASCADE,
    CONSTRAINT fk_wave_order_order FOREIGN KEY (order_id)
        REFERENCES orders(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 15. Pick Tasks table: consolidated SKU-level warehouse picking stops
CREATE TABLE pick_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wave_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    required_quantity INT NOT NULL DEFAULT 1,
    picked_quantity INT NOT NULL DEFAULT 0,
    shelf_id INT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    aisle_zone VARCHAR(100) NULL,
    sequence_order INT NOT NULL DEFAULT 0,
    exception_reason TEXT NULL,
    picked_at TIMESTAMP NULL,
    order_allocations TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_task_wave FOREIGN KEY (wave_id)
        REFERENCES waves(id) ON DELETE CASCADE,
    CONSTRAINT fk_task_product FOREIGN KEY (product_id)
        REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 16. Inventory Reservations table: stock holds for waves in progress
CREATE TABLE inventory_reservations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wave_id VARCHAR(50) NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    status VARCHAR(50) NOT NULL DEFAULT 'Reserved',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_res_wave FOREIGN KEY (wave_id)
        REFERENCES waves(id) ON DELETE CASCADE,
    CONSTRAINT fk_res_product FOREIGN KEY (product_id)
        REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 17. Wave Exceptions table: audit tracking for shortages and obstacles
CREATE TABLE wave_exceptions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wave_id VARCHAR(50) NOT NULL,
    task_id INT NULL,
    product_id INT NULL,
    exception_type VARCHAR(50) NOT NULL,
    details TEXT NOT NULL,
    resolved TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_exc_wave FOREIGN KEY (wave_id)
        REFERENCES waves(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 18. Layout Snapshots table: snapshot history for undoing and auditing warehouse re-slotting
CREATE TABLE layout_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    strategy VARCHAR(50) NOT NULL DEFAULT 'velocity',
    assignments_json MEDIUMTEXT NOT NULL,
    travel_index_before FLOAT NOT NULL DEFAULT 0.0,
    travel_index_after FLOAT NOT NULL DEFAULT 0.0,
    reduction_pct FLOAT NOT NULL DEFAULT 0.0,
    user_email VARCHAR(120) NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'applied',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
