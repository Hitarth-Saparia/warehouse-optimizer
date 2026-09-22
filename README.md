# Warehouse Layout & Order Picking Optimizer

A web application demonstrating warehouse inventory layout optimization and graph-based order picking route minimization.

Built with a strict, minimal 3-folder architecture (`frontend/`, `backend/`, `database/`) designed for clear comprehension, maintainability, and educational viva/demo presentations.

---

## Academic & Technical Concept Mapping

| Core Academic Subject | Concept / Algorithm | Implementation File & Details |
| :--- | :--- | :--- |
| **DBMS (Database Systems)** | Relational Schema & Queries | [`database/schema.sql`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/database/schema.sql), [`database/seed.py`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/database/seed.py)<br>Tables: `shelves`, `products`, `sales`, `orders`, `order_items`, `edges`. Real SQL queries join tables to calculate pick frequencies and dynamic shelf loads. |
| **Object-Oriented Programming (OOP)** | Domain Modeling | [`backend/models.py`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/backend/models.py)<br>Clean classes: `Product`, `Shelf`, `Order`, `Worker` representing physical warehouse entities. |
| **Discrete Mathematics & Graph Theory** | Graph Representation & Dijkstra Shortest Path | [`backend/warehouse.py`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/backend/warehouse.py)<br>Undirected weighted graph $G = (V, E)$ built from shelves and aisle corridors. Shortest corridor distances are computed using Dijkstra's Algorithm with a min-heap priority queue (`heapq`). |
| **Optimization Algorithms** | Greedy Heuristic Slotting | [`backend/layout_optimizer.py`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/backend/layout_optimizer.py)<br>1. Sort products descending by pick frequency (sales volume).<br>2. Sort storage shelves ascending by distance to packing hub.<br>3. Greedily place high-velocity products on closest shelves.<br>4. Enforce shelf capacity limits and separate incompatible categories (Fragile vs. Heavy). |
| **Optimization Algorithms** | Traveling Salesperson Problem (TSP) | [`backend/route_optimizer.py`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/backend/route_optimizer.py)<br>Solves the shortest round-trip picking tour starting and ending at Packing (Shelf 1).<br>• If unique stops $< 8$: **Brute-Force Permutation** (`itertools.permutations`) guarantees exact global minimum.<br>• If unique stops $\ge 8$: **Nearest-Neighbor Heuristic** provides polynomial greedy fallback. |
| **Empirical Evaluation** | Before vs. After Optimization Proof | [`backend/comparison.py`](file:///Users/hitarthsaparia/Documents/warehouse_optimizer/backend/comparison.py)<br>Simulates sample orders across random vs. optimized shelf layouts, demonstrating ~32% reduction in worker travel distance. |

---

## Directory Structure

```
warehouse_optimizer/
├── database/
│   ├── schema.sql            # Table definitions (shelves, products, sales, orders, order_items, edges)
│   └── seed.py               # Deterministic seed script (25 shelves, 60 products, sales history, 12 orders)
├── backend/
│   ├── app.py                # Flask REST API + static page server
│   ├── models.py             # Product, Shelf, Order, Worker classes
│   ├── warehouse.py          # Warehouse graph model + Dijkstra shortest-path algorithm
│   ├── layout_optimizer.py   # Greedy frequency-based slotting + capacity & safety constraints
│   ├── route_optimizer.py    # TSP route optimizer (Brute-Force Permutation & Nearest-Neighbor fallback)
│   ├── comparison.py         # Empirical before vs. after comparison calculation
│   └── requirements.txt      # Python dependencies (flask, flask-cors, pymysql)
├── frontend/
│   ├── style.css             # Single shared stylesheet for all 5 pages
│   ├── index.html            # Dashboard: totals and live Before vs. After distance comparison
│   ├── products.html         # Table: products, categories, assigned shelves, pick frequencies
│   ├── layout.html           # Side-by-side old vs. new shelf allocation diff + Save Layout button
│   ├── graph.html            # Visual warehouse graph canvas (shelves, packing station, distances)
│   └── order-picking.html    # Order picker: order dropdown, TSP algorithm badge, ordered stops list
└── README.md                 # Project documentation and demo walkthrough guide
```

---

### Quick Start (Recommended)
You can use the helper script `run.sh` to run the application with a single command:
```bash
# Make executable (if needed) and run
chmod +x run.sh

# Option A: Start the web application directly
./run.sh

# Option B: Initialize/seed the database and start the server in one go
./run.sh --seed

# Option C: Seed the database only
./run.sh seed
```

---

### Manual Setup & Running Instructions
```bash
# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r backend/requirements.txt
```

### 3. Initialize & Seed MySQL Database
Run the seed script to automatically create the `wareopt` database, apply `database/schema.sql`, and insert sample data:
```bash
python database/seed.py
```
This sets up:
- **25 Shelves**: Shelf 1 is the Packing & Dispatch Hub (distance 0m), plus Shelves 2–25 distributed across 4 warehouse storage aisles.
- **Corridor Edges**: Graph connectivity between adjacent shelves and cross-aisles.
- **60 Products**: Categorized as Electronics, Fasteners, Tools, Safety, Fragile, and Heavy.
- **6 Months of Sales**: Used to calculate Pareto pick frequency.
- **12 Sample Orders**: Orders 1–9 test exact Brute-Force TSP ($< 8$ stops); Orders 10–12 test Nearest-Neighbor fallback ($\ge 8$ stops).

### 4. Start the Backend Server
```bash
python backend/app.py
```
The Flask server starts at:
👉 **`http://127.0.0.1:5001`**

### 5. Access the Frontend Pages
Open your browser to any of the 5 pages:
- **Dashboard**: `http://127.0.0.1:5001/index.html` (or `http://127.0.0.1:5001/`)
- **Products Catalog**: `http://127.0.0.1:5001/products.html`
- **Layout Optimizer**: `http://127.0.0.1:5001/layout.html`
- **Warehouse Graph**: `http://127.0.0.1:5001/graph.html`
- **Order Picking**: `http://127.0.0.1:5001/order-picking.html`

---

## Demo & Viva Walkthrough Steps

1. **Dashboard (`index.html`)**:
   - Point out the summary cards (60 products, 25 shelves, 12 orders).
   - Explain the **Before vs After Optimization** banner proving ~32% reduction in walking distance.
   - Show the per-order breakdown table where each customer order was evaluated under both layouts using graph shortest paths.

2. **Products (`products.html`)**:
   - Show the catalog of 60 items with category, assigned shelf, and pick frequency.
   - Explain that pick frequency is dynamically calculated via `SUM(sales.units_sold)`.
   - Filter by categories like `Heavy` or `Fragile` to demonstrate safety constraints.

3. **Layout Optimizer (`layout.html`)**:
   - Click **"Run Layout Optimizer"**.
   - Walk through the side-by-side table: high-velocity items are moved from distant shelves to shelves closer to the Packing Station.
   - Point out that Fragile and Heavy items are never placed together on the same shelf, and shelf capacity ($\le 5$) is never exceeded.
   - Click **"Save Layout to MySQL"** to update `products.assigned_shelf_id` in the database.

4. **Warehouse Graph (`graph.html`)**:
   - Show the 2D floorplan canvas showing the Packing Station (green) and storage shelves (blue) connected by corridor edges.
   - Click on any shelf node (e.g. Shelf 5) to inspect its distance to packing, current load, and direct aisle connections.

5. **Order Picking (`order-picking.html`)**:
   - Select **Order #1** and click **"Compute Picking Route"**.
   - Show that with $<8$ stops, the system selects **"Brute-Force Permutation (Exact TSP)"** to guarantee the shortest possible round trip.
   - Next, select **Order #11** ($>8$ stops) and click **"Compute Picking Route"**.
   - Observe the badge change to **"Nearest-Neighbor Heuristic (Greedy TSP Fallback)"**, explaining why polynomial approximation is needed for larger orders.
   - View the red highlighted route path on the floorplan canvas and the step-by-step picking sequence.
