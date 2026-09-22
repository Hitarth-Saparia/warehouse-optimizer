-- Warehouse Layout & Order Picking Optimizer
-- Database Schema for MySQL

CREATE DATABASE IF NOT EXISTS wareopt;
USE wareopt;

SET FOREIGN_KEY_CHECKS = 0;
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

-- 4. Orders table: customer orders to be picked
CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(150) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Pending'
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
