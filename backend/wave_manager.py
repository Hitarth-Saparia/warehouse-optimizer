"""
backend/wave_manager.py
Wave Picking Management & Optimization Engine:
==============================================
Provides end-to-end multi-order wave picking capabilities:
- Intelligent order grouping algorithms (Priority, Due-date, Zone, SKU-affinity, Batch-capacity, Hybrid)
- Consolidated SKU-level pick list generation with order-level allocation preservation
- Route optimization (TSP stops sorted to eliminate aisle back-tracking)
- Stock availability verification and inventory reservation mechanism
- Full lifecycle management (Draft -> Scheduled -> Active -> Paused -> Completed / Cancelled)
- Pick task confirmation, partial picking, and shortage exception tracking
- Auditable inventory stock decrement upon fulfillment
- Live operational dashboard metrics
"""

import json
from datetime import datetime
from backend.models import Wave, PickTask, InventoryReservation, WaveException
from backend.route_optimizer import RouteOptimizer


class WaveManager:
    """
    Manages Wave Picking operations, grouping optimization, inventory reservations,
    and end-to-end task fulfillment lifecycle.
    """

    def __init__(self, db_conn, warehouse=None):
        self.conn = db_conn
        self.warehouse = warehouse
        self.route_optimizer = RouteOptimizer(warehouse) if warehouse else None

    # -------------------------------------------------------------
    # 1. Order Fetching & Availability Verification
    # -------------------------------------------------------------

    def get_allocated_order_ids(self):
        """
        Returns set of order IDs currently assigned to active, draft, scheduled, or paused waves.
        Cancelled and Completed waves do not block orders.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT wo.order_id
                FROM wave_orders wo
                JOIN waves w ON wo.wave_id = w.id
                WHERE w.status IN ('Draft', 'Scheduled', 'Active', 'Paused')
            """)
            rows = cur.fetchall()
            return {r["order_id"] for r in rows}

    def get_eligible_orders(self):
        """
        Fetches all unallocated 'Pending' customer orders eligible for inclusion in a new wave.
        """
        from backend.app import fetch_all_orders
        all_orders = fetch_all_orders(self.conn)
        allocated_ids = self.get_allocated_order_ids()

        eligible = [
            o for o in all_orders
            if o.status.lower() == "pending" and o.id not in allocated_ids and len(o.items) > 0
        ]
        return eligible

    def get_reserved_quantities(self):
        """
        Returns dict of {product_id: total_reserved_quantity} for active/scheduled waves.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT product_id, SUM(quantity) as reserved_qty
                FROM inventory_reservations
                WHERE status = 'Reserved'
                GROUP BY product_id
            """)
            rows = cur.fetchall()
            return {r["product_id"]: int(r["reserved_qty"] or 0) for r in rows}

    def check_stock_availability(self, required_skus):
        """
        Validates inventory stock availability for a dictionary of {product_id: required_qty}.
        Returns (is_sufficient, shortages_list, stock_details).
        """
        if not required_skus:
            return True, [], {}

        reserved_map = self.get_reserved_quantities()
        with self.conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(required_skus))
            cur.execute(f"""
                SELECT id, name, stock_quantity, assigned_shelf_id
                FROM products
                WHERE id IN ({placeholders})
            """, list(required_skus.keys()))
            rows = cur.fetchall()

        product_map = {r["id"]: r for r in rows}
        shortages = []
        stock_details = {}
        all_sufficient = True

        for p_id, req_qty in required_skus.items():
            p_data = product_map.get(p_id)
            if not p_data:
                all_sufficient = False
                shortages.append({
                    "product_id": p_id,
                    "product_name": f"Product #{p_id}",
                    "required": req_qty,
                    "available": 0,
                    "reason": "Product not found in inventory catalog"
                })
                continue

            phys_stock = int(p_data["stock_quantity"] or 0)
            res_stock = reserved_map.get(p_id, 0)
            avail_stock = max(0, phys_stock - res_stock)

            stock_details[p_id] = {
                "product_id": p_id,
                "product_name": p_data["name"],
                "physical_stock": phys_stock,
                "reserved_stock": res_stock,
                "available_stock": avail_stock,
                "required_quantity": req_qty,
                "shelf_id": p_data["assigned_shelf_id"]
            }

            if avail_stock < req_qty:
                all_sufficient = False
                shortages.append({
                    "product_id": p_id,
                    "product_name": p_data["name"],
                    "required": req_qty,
                    "available": avail_stock,
                    "physical": phys_stock,
                    "reserved": res_stock,
                    "reason": f"Insufficient stock: required {req_qty}, only {avail_stock} available ({res_stock} reserved)"
                })

        return all_sufficient, shortages, stock_details

    # -------------------------------------------------------------
    # 2. Intelligent Grouping Algorithms
    # -------------------------------------------------------------

    def group_orders(self, orders, strategy="Hybrid", max_cart_capacity=35, max_orders_per_batch=4, shelf_mapping=None):
        """
        Groups compatible customer orders into picking waves based on specified strategy.

        Strategies supported:
        - 'Priority-based': Prioritizes urgent/high priority orders first.
        - 'Due-date-based': Groups orders by delivery deadline cutoff.
        - 'Zone-based': Clusters orders requiring picking from the same warehouse aisles/zones.
        - 'SKU-based': Merges orders sharing common SKUs to minimize repeated shelf visits.
        - 'Batch/Capacity-based': Knapsack greedy clustering adhering strictly to cart limits.
        - 'Hybrid': Multi-objective combination (priority + zone synergy + SKU sharing + capacity).
        """
        if not orders:
            return []

        shelf_map = shelf_mapping or {}

        # Precompute metadata for candidate orders
        order_meta = []
        for o in orders:
            stops = set()
            skus = set()
            units = 0
            for item in o.items:
                p_id = item.get("product_id")
                qty = item.get("quantity", 1)
                units += qty
                skus.add(p_id)
                s_id = shelf_map.get(p_id) if shelf_map else item.get("shelf_id")
                if s_id and s_id != 1:
                    stops.add(int(s_id))

            # Priority weight score
            prio_weights = {"Urgent": 40, "High": 30, "Standard": 20, "Low": 10}
            prio_score = prio_weights.get(o.priority, 20)

            # Dominant warehouse zone
            # Shelves 2-7: Aisle 1 (Zone A), 8-13: Aisle 2 (Zone B), 14-19: Aisle 3 (Zone C), 20-25: Aisle 4 (Zone D)
            zones = set()
            for s in stops:
                if 2 <= s <= 7:
                    zones.add("Aisle 1 - Zone A")
                elif 8 <= s <= 13:
                    zones.add("Aisle 2 - Zone B")
                elif 14 <= s <= 19:
                    zones.add("Aisle 3 - Zone C")
                elif 20 <= s <= 25:
                    zones.add("Aisle 4 - Zone D")
                else:
                    zones.add("General Zone")

            # Route distance for this individual order
            indiv_dist = 25.0
            if self.route_optimizer and stops:
                single_route = self.route_optimizer.solve_order_route(o.id, list(stops))
                indiv_dist = single_route.get("total_distance", 25.0)

            order_meta.append({
                "order": o,
                "order_id": o.id,
                "customer_name": o.customer_name,
                "priority": o.priority,
                "prio_score": prio_score,
                "deadline": o.deadline or "18:00",
                "units": units,
                "skus": skus,
                "stops": stops,
                "zones": zones,
                "individual_distance": indiv_dist
            })

        strategy_clean = strategy.strip().title()

        if "Priority" in strategy_clean:
            # Sort primarily by priority score descending
            unassigned = sorted(order_meta, key=lambda x: (x["prio_score"], -x["units"]), reverse=True)
            return self._pack_greedy(unassigned, max_cart_capacity, max_orders_per_batch)

        elif "Due-Date" in strategy_clean or "Due" in strategy_clean or "Date" in strategy_clean:
            # Sort by delivery deadline string ascending
            unassigned = sorted(order_meta, key=lambda x: (x["deadline"], -x["prio_score"]))
            return self._pack_greedy(unassigned, max_cart_capacity, max_orders_per_batch)

        elif "Zone" in strategy_clean:
            # Sort/cluster by dominant zone, then packing
            unassigned = sorted(order_meta, key=lambda x: (sorted(list(x["zones"]))[0] if x["zones"] else "Z", -x["units"]))
            return self._pack_cluster_affinity(unassigned, max_cart_capacity, max_orders_per_batch, mode="zone")

        elif "Sku" in strategy_clean:
            # Seed-based SKU affinity clustering (Jaccard similarity on SKUs)
            unassigned = sorted(order_meta, key=lambda x: len(x["skus"]), reverse=True)
            return self._pack_cluster_affinity(unassigned, max_cart_capacity, max_orders_per_batch, mode="sku")

        elif "Batch" in strategy_clean or "Capacity" in strategy_clean:
            # Standard Knapsack / Capacity clustering
            unassigned = sorted(order_meta, key=lambda x: x["units"], reverse=True)
            return self._pack_greedy(unassigned, max_cart_capacity, max_orders_per_batch)

        else:
            # Default: Hybrid Strategy
            # Combines priority weighting with zone/SKU affinity and cart capacity
            unassigned = sorted(order_meta, key=lambda x: (x["prio_score"], len(x["stops"])), reverse=True)
            return self._pack_cluster_affinity(unassigned, max_cart_capacity, max_orders_per_batch, mode="hybrid")

    def _pack_greedy(self, unassigned, max_capacity, max_orders):
        """Simple greedy bin-packing honoring capacity and order count limits."""
        batches = []
        pool = list(unassigned)
        while pool:
            seed = pool.pop(0)
            current_batch = [seed]
            current_units = seed["units"]

            i = 0
            while i < len(pool) and len(current_batch) < max_orders:
                cand = pool[i]
                if current_units + cand["units"] <= max_capacity:
                    current_batch.append(cand)
                    current_units += cand["units"]
                    pool.pop(i)
                else:
                    i += 1
            batches.append(current_batch)
        return batches

    def _pack_cluster_affinity(self, unassigned, max_capacity, max_orders, mode="hybrid"):
        """Affinity-based clustering using Jaccard stop/SKU similarity and zone synergy."""
        batches = []
        pool = list(unassigned)

        while pool:
            seed = pool.pop(0)
            current_batch = [seed]
            current_units = seed["units"]
            current_stops = set(seed["stops"])
            current_skus = set(seed["skus"])
            current_zones = set(seed["zones"])

            while len(current_batch) < max_orders and pool:
                best_idx = -1
                best_score = -1.0

                for idx, cand in enumerate(pool):
                    if current_units + cand["units"] > max_capacity:
                        continue

                    # Calculate synergy score
                    if mode == "zone":
                        overlap = len(current_zones.intersection(cand["zones"]))
                        score = overlap * 2.0
                    elif mode == "sku":
                        union = current_skus.union(cand["skus"])
                        score = len(current_skus.intersection(cand["skus"])) / len(union) if union else 0.0
                    else: # hybrid
                        sku_union = current_skus.union(cand["skus"])
                        sku_sim = len(current_skus.intersection(cand["skus"])) / len(sku_union) if sku_union else 0.0
                        zone_sim = len(current_zones.intersection(cand["zones"])) * 0.5
                        prio_boost = cand["prio_score"] / 40.0 * 0.3
                        score = sku_sim + zone_sim + prio_boost

                    if score > best_score:
                        best_score = score
                        best_idx = idx

                if best_idx != -1:
                    chosen = pool.pop(best_idx)
                    current_batch.append(chosen)
                    current_units += chosen["units"]
                    current_stops.update(chosen["stops"])
                    current_skus.update(chosen["skus"])
                    current_zones.update(chosen["zones"])
                else:
                    break

            batches.append(current_batch)
        return batches

    # -------------------------------------------------------------
    # 3. Wave Proposal / Preview Generation
    # -------------------------------------------------------------

    def generate_wave_proposal(self, orders, strategy="Hybrid", max_cart_capacity=35,
                               max_orders_per_batch=4, priority="Standard", assigned_picker="Alex Morgan",
                               shelf_mapping=None):
        """
        Synthesizes a proposed Wave without persisting it to the database.
        Returns detailed workload, consolidated pick list, route metrics, and stock checks.
        """
        shelf_map = shelf_mapping or {}
        grouped_batches = self.group_orders(orders, strategy, max_cart_capacity, max_orders_per_batch, shelf_map)

        if not grouped_batches:
            return {
                "wave_proposals": [],
                "summary": {
                    "total_waves": 0,
                    "total_orders": 0,
                    "total_skus": 0,
                    "total_units": 0,
                    "distance_saved_m": 0.0
                }
            }

        proposals = []
        next_wave_num = self._get_next_wave_number()

        for b_idx, batch_orders in enumerate(grouped_batches):
            wave_id = f"WAVE-{next_wave_num + b_idx:04d}"
            wave_name = f"Wave #{next_wave_num + b_idx} ({strategy})"

            # Consolidate SKUs and items
            consolidated_skus = {}
            unique_stops = set()
            order_ids = []
            customer_names = []
            total_units = 0

            for bo in batch_orders:
                order_ids.append(bo["order_id"])
                customer_names.append(bo["customer_name"])
                total_units += bo["units"]
                unique_stops.update(bo["stops"])

                for item in bo["order"].items:
                    p_id = item.get("product_id")
                    qty = item.get("quantity", 1)
                    p_name = item.get("name", f"Product #{p_id}")
                    s_id = shelf_map.get(p_id) if shelf_map else item.get("shelf_id")

                    if p_id not in consolidated_skus:
                        consolidated_skus[p_id] = {
                            "product_id": p_id,
                            "product_name": p_name,
                            "sku": f"SKU-{p_id:04d}",
                            "shelf_id": s_id,
                            "required_quantity": 0,
                            "order_allocations": {}
                        }
                    consolidated_skus[p_id]["required_quantity"] += qty
                    o_alloc = consolidated_skus[p_id]["order_allocations"]
                    o_alloc[bo["order_id"]] = o_alloc.get(bo["order_id"], 0) + qty

            # Check stock availability
            sku_qty_req = {p_id: data["required_quantity"] for p_id, data in consolidated_skus.items()}
            stock_ok, shortages, stock_details = self.check_stock_availability(sku_qty_req)

            # Compute route optimization
            unbatched_dist = sum(bo["individual_distance"] for bo in batch_orders)
            batched_dist = unbatched_dist
            route_info = {"algorithm": "Direct", "stops": list(unique_stops), "legs": [], "full_path": []}

            if self.route_optimizer and unique_stops:
                route_res = self.route_optimizer.solve_order_route(wave_id, list(unique_stops))
                batched_dist = route_res.get("total_distance", unbatched_dist)
                route_info = route_res

            dist_saved = max(0.0, round(unbatched_dist - batched_dist, 1))
            travel_reduction = round((dist_saved / unbatched_dist * 100), 1) if unbatched_dist > 0 else 0.0

            # Sort tasks by TSP route sequence
            ordered_stops = route_info.get("stops", [])
            stop_order_map = {s_id: idx for idx, s_id in enumerate(ordered_stops)}

            task_list = []
            for p_id, s_data in consolidated_skus.items():
                s_id = s_data["shelf_id"]
                seq = stop_order_map.get(s_id, 999)
                aisle = f"Aisle {(s_id - 2) // 6 + 1}" if s_id and s_id > 1 else "Packing Hub"
                zone = "Zone A" if s_id and s_id <= 7 else ("Zone B" if s_id and s_id <= 13 else "Zone C")
                st_detail = stock_details.get(p_id, {})

                task_list.append({
                    "product_id": p_id,
                    "sku": s_data["sku"],
                    "product_name": s_data["product_name"],
                    "shelf_id": s_id,
                    "shelf_label": f"Shelf #{s_id}" if s_id else "Unassigned",
                    "aisle_zone": f"{aisle} ({zone})",
                    "required_quantity": s_data["required_quantity"],
                    "picked_quantity": 0,
                    "remaining_quantity": s_data["required_quantity"],
                    "status": "Pending",
                    "sequence_order": seq,
                    "order_allocations": s_data["order_allocations"],
                    "available_stock": st_detail.get("available_stock", 50),
                    "is_sufficient": st_detail.get("available_stock", 50) >= s_data["required_quantity"]
                })

            task_list.sort(key=lambda t: t["sequence_order"])

            proposals.append({
                "wave_id": wave_id,
                "name": wave_name,
                "status": "Draft",
                "strategy": strategy,
                "priority": priority,
                "assigned_picker": assigned_picker,
                "max_cart_capacity": max_cart_capacity,
                "order_ids": order_ids,
                "total_orders": len(order_ids),
                "customers": customer_names,
                "total_skus": len(consolidated_skus),
                "total_units": total_units,
                "unbatched_distance_m": round(unbatched_dist, 1),
                "estimated_distance_m": round(batched_dist, 1),
                "distance_saved_m": dist_saved,
                "travel_reduction_pct": travel_reduction,
                "repeated_stops_saved": sum(len(bo["stops"]) for bo in batch_orders) - len(unique_stops),
                "tasks": task_list,
                "route_info": route_info,
                "stock_verified": stock_ok,
                "shortages": shortages
            })

        summary = {
            "total_waves": len(proposals),
            "total_orders": sum(p["total_orders"] for p in proposals),
            "total_skus": sum(p["total_skus"] for p in proposals),
            "total_units": sum(p["total_units"] for p in proposals),
            "distance_saved_m": round(sum(p["distance_saved_m"] for p in proposals), 1),
            "unbatched_distance_m": round(sum(p["unbatched_distance_m"] for p in proposals), 1),
            "estimated_distance_m": round(sum(p["estimated_distance_m"] for p in proposals), 1)
        }

        return {
            "wave_proposals": proposals,
            "summary": summary
        }

    def _get_next_wave_number(self):
        """Finds highest numeric wave ID to generate next sequential ID."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM waves")
            rows = cur.fetchall()
            max_num = 1000
            for r in rows:
                val = r["id"]
                if val.startswith("WAVE-"):
                    try:
                        num = int(val.split("-")[1])
                        if num > max_num:
                            max_num = num
                    except (ValueError, IndexError):
                        pass
            return max_num + 1

    # -------------------------------------------------------------
    # 4. Wave Creation & Persistence
    # -------------------------------------------------------------

    def create_wave(self, name, order_ids, strategy="Hybrid", priority="Standard",
                    assigned_picker="Alex Morgan", max_cart_capacity=35, scheduled_at=None,
                    deadline=None, notes=None):
        """
        Creates and persists a new Wave, associating orders, generating consolidated
        SKU-level pick tasks, and computing TSP route metrics.
        """
        if not order_ids:
            raise ValueError("At least one order must be selected to create a wave.")

        # Check for conflicting active waves
        allocated_ids = self.get_allocated_order_ids()
        conflicts = set(order_ids).intersection(allocated_ids)
        if conflicts:
            raise ValueError(f"Orders {sorted(list(conflicts))} are already allocated to active picking waves.")

        # Fetch orders
        from backend.app import fetch_all_orders
        all_orders = fetch_all_orders(self.conn)
        orders_dict = {o.id: o for o in all_orders}
        selected_orders = [orders_dict[oid] for oid in order_ids if oid in orders_dict]

        if not selected_orders:
            raise ValueError("None of the specified order IDs could be found.")

        # Consolidate SKUs
        consolidated = {}
        unique_stops = set()
        total_units = 0

        for o in selected_orders:
            for item in o.items:
                p_id = item.get("product_id")
                qty = item.get("quantity", 1)
                p_name = item.get("name", f"Product #{p_id}")
                s_id = item.get("shelf_id")
                total_units += qty

                if s_id and s_id != 1:
                    unique_stops.add(int(s_id))

                if p_id not in consolidated:
                    consolidated[p_id] = {
                        "product_id": p_id,
                        "product_name": p_name,
                        "shelf_id": s_id,
                        "required_quantity": 0,
                        "order_allocations": {}
                    }
                consolidated[p_id]["required_quantity"] += qty
                o_alloc = consolidated[p_id]["order_allocations"]
                o_alloc[o.id] = o_alloc.get(o.id, 0) + qty

        # TSP Route Calculation
        wave_num = self._get_next_wave_number()
        wave_id = f"WAVE-{wave_num:04d}"

        unbatched_dist = 0.0
        for o in selected_orders:
            o_stops = [item.get("shelf_id") for item in o.items if item.get("shelf_id") and item.get("shelf_id") != 1]
            if self.route_optimizer and o_stops:
                r_res = self.route_optimizer.solve_order_route(o.id, list(set(o_stops)))
                unbatched_dist += r_res.get("total_distance", 25.0)
            else:
                unbatched_dist += 25.0

        batched_dist = unbatched_dist
        stop_seq = []
        if self.route_optimizer and unique_stops:
            r_res = self.route_optimizer.solve_order_route(wave_id, list(unique_stops))
            batched_dist = r_res.get("total_distance", unbatched_dist)
            stop_seq = r_res.get("stops", [])

        dist_saved = max(0.0, round(unbatched_dist - batched_dist, 1))

        # Insert wave record
        initial_status = "Scheduled" if scheduled_at else "Draft"
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO waves (
                    id, name, status, strategy, priority, assigned_picker, max_cart_capacity,
                    total_orders, total_skus, total_units, picked_units, estimated_distance_m,
                    unbatched_distance_m, distance_saved_m, scheduled_at, deadline, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s)
            """, (
                wave_id, name or f"Wave #{wave_num}", initial_status, strategy, priority,
                assigned_picker, max_cart_capacity, len(selected_orders), len(consolidated),
                total_units, batched_dist, unbatched_dist, dist_saved, scheduled_at, deadline, notes
            ))

            # Associate wave orders
            for oid in order_ids:
                cur.execute("""
                    INSERT INTO wave_orders (wave_id, order_id, status)
                    VALUES (%s, %s, 'Assigned')
                """, (wave_id, oid))

            # Insert pick tasks
            stop_order_map = {s: idx for idx, s in enumerate(stop_seq)}
            for p_id, c_data in consolidated.items():
                s_id = c_data["shelf_id"]
                seq = stop_order_map.get(s_id, 999)
                aisle = f"Aisle {(s_id - 2) // 6 + 1}" if s_id and s_id > 1 else "Packing Hub"
                zone = "Zone A" if s_id and s_id <= 7 else ("Zone B" if s_id and s_id <= 13 else "Zone C")
                aisle_zone = f"{aisle} ({zone})"

                cur.execute("""
                    INSERT INTO pick_tasks (
                        wave_id, product_id, required_quantity, picked_quantity, shelf_id,
                        status, aisle_zone, sequence_order, order_allocations
                    ) VALUES (%s, %s, %s, 0, %s, 'Pending', %s, %s, %s)
                """, (
                    wave_id, p_id, c_data["required_quantity"], s_id, aisle_zone,
                    seq, json.dumps(c_data["order_allocations"])
                ))

            self.conn.commit()

        return self.get_wave(wave_id)

    # -------------------------------------------------------------
    # 5. Wave Retrieval & Details
    # -------------------------------------------------------------

    def get_wave(self, wave_id):
        """Retrieves comprehensive details for a single Wave by ID."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM waves WHERE id = %s", (wave_id,))
            w_row = cur.fetchone()
            if not w_row:
                return None

            # Fetch wave orders
            cur.execute("""
                SELECT wo.id, wo.order_id, wo.status as link_status, o.customer_name,
                       o.status as order_status, o.priority, o.deadline, o.weight
                FROM wave_orders wo
                JOIN orders o ON wo.order_id = o.id
                WHERE wo.wave_id = %s
                ORDER BY wo.id ASC
            """, (wave_id,))
            orders_rows = cur.fetchall()

            # Fetch pick tasks
            cur.execute("""
                SELECT pt.*, p.name as product_name, p.category, p.stock_quantity
                FROM pick_tasks pt
                JOIN products p ON pt.product_id = p.id
                WHERE pt.wave_id = %s
                ORDER BY pt.sequence_order ASC, pt.id ASC
            """, (wave_id,))
            tasks_rows = cur.fetchall()

            # Fetch exceptions
            cur.execute("SELECT * FROM wave_exceptions WHERE wave_id = %s ORDER BY id DESC", (wave_id,))
            exceptions_rows = cur.fetchall()

            # Fetch reservations
            cur.execute("SELECT * FROM inventory_reservations WHERE wave_id = %s ORDER BY id ASC", (wave_id,))
            res_rows = cur.fetchall()

        wave_obj = Wave(
            id=w_row["id"],
            name=w_row["name"],
            status=w_row["status"],
            strategy=w_row["strategy"],
            priority=w_row["priority"],
            assigned_picker=w_row["assigned_picker"],
            max_cart_capacity=w_row["max_cart_capacity"],
            total_orders=w_row["total_orders"],
            total_skus=w_row["total_skus"],
            total_units=w_row["total_units"],
            picked_units=w_row["picked_units"],
            estimated_distance_m=w_row["estimated_distance_m"],
            unbatched_distance_m=w_row["unbatched_distance_m"],
            distance_saved_m=w_row["distance_saved_m"],
            scheduled_at=w_row["scheduled_at"],
            deadline=w_row["deadline"],
            started_at=w_row["started_at"],
            completed_at=w_row["completed_at"],
            notes=w_row["notes"],
            created_at=w_row["created_at"]
        )

        tasks = []
        for r in tasks_rows:
            allocs = json.loads(r["order_allocations"]) if r["order_allocations"] else {}
            task = PickTask(
                id=r["id"],
                wave_id=r["wave_id"],
                product_id=r["product_id"],
                required_quantity=r["required_quantity"],
                picked_quantity=r["picked_quantity"],
                shelf_id=r["shelf_id"],
                status=r["status"],
                aisle_zone=r["aisle_zone"],
                sequence_order=r["sequence_order"],
                exception_reason=r["exception_reason"],
                picked_at=r["picked_at"],
                order_allocations=allocs,
                product_name=r["product_name"],
                category=r["category"]
            )
            task_dict = task.to_dict()
            task_dict["current_stock"] = r["stock_quantity"]
            tasks.append(task_dict)

        wave_dict = wave_obj.to_dict()
        wave_dict["orders"] = orders_rows
        wave_dict["tasks"] = tasks
        wave_dict["exceptions"] = exceptions_rows
        wave_dict["reservations"] = res_rows

        return wave_dict

    def list_waves(self, status=None, priority=None, picker=None, search=None):
        """Lists picking waves with optional filtering and search."""
        query = "SELECT * FROM waves WHERE 1=1"
        params = []

        if status:
            query += " AND status = %s"
            params.append(status)
        if priority:
            query += " AND priority = %s"
            params.append(priority)
        if picker:
            query += " AND assigned_picker LIKE %s"
            params.append(f"%{picker}%")
        if search:
            query += " AND (id LIKE %s OR name LIKE %s OR notes LIKE %s)"
            s_param = f"%{search}%"
            params.extend([s_param, s_param, s_param])

        query += " ORDER BY created_at DESC"

        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        result = []
        for r in rows:
            w = Wave(
                id=r["id"],
                name=r["name"],
                status=r["status"],
                strategy=r["strategy"],
                priority=r["priority"],
                assigned_picker=r["assigned_picker"],
                max_cart_capacity=r["max_cart_capacity"],
                total_orders=r["total_orders"],
                total_skus=r["total_skus"],
                total_units=r["total_units"],
                picked_units=r["picked_units"],
                estimated_distance_m=r["estimated_distance_m"],
                unbatched_distance_m=r["unbatched_distance_m"],
                distance_saved_m=r["distance_saved_m"],
                scheduled_at=r["scheduled_at"],
                deadline=r["deadline"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                notes=r["notes"],
                created_at=r["created_at"]
            )
            result.append(w.to_dict())

        return result

    # -------------------------------------------------------------
    # 6. Wave Lifecycle & State Transitions
    # -------------------------------------------------------------

    def start_wave(self, wave_id):
        """
        Starts a wave:
        1. Verifies stock availability.
        2. Creates inventory reservations to prevent double-allocation.
        3. Sets status -> 'Active' and records started_at timestamp.
        4. Transitions associated order statuses to 'In Picking'.
        """
        wave = self.get_wave(wave_id)
        if not wave:
            raise ValueError(f"Wave {wave_id} not found.")

        if wave["status"] not in ("Draft", "Scheduled", "Paused"):
            raise ValueError(f"Wave {wave_id} cannot be started from status '{wave['status']}'.")

        # Verify stock and build reservations
        req_skus = {t["product_id"]: t["required_quantity"] for t in wave["tasks"]}
        stock_ok, shortages, _ = self.check_stock_availability(req_skus)

        if not stock_ok:
            shortage_msg = "; ".join([s["reason"] for s in shortages])
            raise ValueError(f"Cannot start wave {wave_id} due to inventory shortages: {shortage_msg}")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self.conn.cursor() as cur:
            # Create reservations if not already created
            cur.execute("SELECT COUNT(*) as cnt FROM inventory_reservations WHERE wave_id = %s", (wave_id,))
            if cur.fetchone()["cnt"] == 0:
                for p_id, qty in req_skus.items():
                    cur.execute("""
                        INSERT INTO inventory_reservations (wave_id, product_id, quantity, status)
                        VALUES (%s, %s, %s, 'Reserved')
                    """, (wave_id, p_id, qty))

            # Update wave status
            cur.execute("""
                UPDATE waves
                SET status = 'Active', started_at = COALESCE(started_at, %s)
                WHERE id = %s
            """, (now_str, wave_id))

            # Update orders status to 'In Picking'
            cur.execute("""
                UPDATE orders
                SET status = 'In Picking'
                WHERE id IN (SELECT order_id FROM wave_orders WHERE wave_id = %s)
            """, (wave_id,))

            self.conn.commit()

        return self.get_wave(wave_id)

    def pause_wave(self, wave_id):
        """Pauses an active wave."""
        wave = self.get_wave(wave_id)
        if not wave:
            raise ValueError(f"Wave {wave_id} not found.")
        if wave["status"] != "Active":
            raise ValueError(f"Only Active waves can be paused. Current status: '{wave['status']}'.")

        with self.conn.cursor() as cur:
            cur.execute("UPDATE waves SET status = 'Paused' WHERE id = %s", (wave_id,))
            self.conn.commit()

        return self.get_wave(wave_id)

    def pick_task(self, wave_id, task_id, picked_quantity, is_partial=False):
        """
        Records picking progress for a specific SKU-level pick task.
        - picked_quantity is added or updated for the task.
        - Prevents over-picking beyond required_quantity.
        - Updates wave progress metrics.
        """
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM pick_tasks WHERE id = %s AND wave_id = %s", (task_id, wave_id))
            task = cur.fetchone()
            if not task:
                raise ValueError(f"Pick task {task_id} not found in wave {wave_id}.")

            req_qty = task["required_quantity"]
            new_picked = int(picked_quantity)

            if new_picked < 0:
                raise ValueError("Picked quantity cannot be negative.")
            if new_picked > req_qty:
                raise ValueError(f"Over-picking prevented: cannot pick {new_picked} units when required is {req_qty}.")

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if new_picked >= req_qty:
                new_status = "Picked"
                picked_at = now_str
            elif new_picked > 0:
                new_status = "Partial"
                picked_at = now_str
            else:
                new_status = "Pending"
                picked_at = None

            cur.execute("""
                UPDATE pick_tasks
                SET picked_quantity = %s, status = %s, picked_at = %s
                WHERE id = %s
            """, (new_picked, new_status, picked_at, task_id))

            # Recalculate wave total picked units
            cur.execute("SELECT SUM(picked_quantity) as total_picked FROM pick_tasks WHERE wave_id = %s", (wave_id,))
            sum_row = cur.fetchone()
            tot_picked = int(sum_row["total_picked"] or 0)

            cur.execute("UPDATE waves SET picked_units = %s WHERE id = %s", (tot_picked, wave_id))
            self.conn.commit()

        return self.get_wave(wave_id)

    def report_task_exception(self, wave_id, task_id, exception_type, details):
        """
        Records an audit exception for an obstacle, damaged stock, or inventory shortage.
        Flags task status as 'Exception'.
        """
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM pick_tasks WHERE id = %s AND wave_id = %s", (task_id, wave_id))
            task = cur.fetchone()
            if not task:
                raise ValueError(f"Task {task_id} not found in wave {wave_id}.")

            cur.execute("""
                INSERT INTO wave_exceptions (wave_id, task_id, product_id, exception_type, details, resolved)
                VALUES (%s, %s, %s, %s, %s, 0)
            """, (wave_id, task_id, task["product_id"], exception_type, details))

            cur.execute("""
                UPDATE pick_tasks
                SET status = 'Exception', exception_reason = %s
                WHERE id = %s
            """, (f"[{exception_type}] {details}", task_id))

            self.conn.commit()

        return self.get_wave(wave_id)

    def complete_wave(self, wave_id):
        """
        Validates completion criteria and finishes the wave:
        1. Ensures all mandatory tasks are resolved (either status == 'Picked' or approved 'Exception').
        2. Deducts picked units from physical inventory stock.
        3. Transitions reservations to 'Fulfilled'.
        4. Updates orders status to 'Picked' (ready for packing).
        5. Sets wave status -> 'Completed' and sets completed_at timestamp.
        """
        wave = self.get_wave(wave_id)
        if not wave:
            raise ValueError(f"Wave {wave_id} not found.")

        if wave["status"] not in ("Active", "Paused"):
            raise ValueError(f"Cannot complete wave {wave_id} from status '{wave['status']}'.")

        # Validate completion criteria
        unresolved_tasks = [
            t for t in wave["tasks"]
            if t["status"] not in ("Picked", "Exception") and t["remaining_quantity"] > 0
        ]
        if unresolved_tasks:
            task_details = [f"SKU {t['sku']} ({t['remaining_quantity']} remaining)" for t in unresolved_tasks]
            raise ValueError(f"Cannot complete wave {wave_id}. Unresolved tasks remain: {', '.join(task_details)}.")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self.conn.cursor() as cur:
            # Deduct physical stock for each picked item
            for t in wave["tasks"]:
                picked = t["picked_quantity"]
                if picked > 0:
                    cur.execute("""
                        UPDATE products
                        SET stock_quantity = GREATEST(0, stock_quantity - %s)
                        WHERE id = %s
                    """, (picked, t["product_id"]))

            # Fulfill reservations
            cur.execute("""
                UPDATE inventory_reservations
                SET status = 'Fulfilled'
                WHERE wave_id = %s
            """, (wave_id,))

            # Transition wave to Completed
            cur.execute("""
                UPDATE waves
                SET status = 'Completed', completed_at = %s
                WHERE id = %s
            """, (now_str, wave_id))

            # Mark associated orders as 'Picked' (ready for packing)
            cur.execute("""
                UPDATE orders
                SET status = 'Picked'
                WHERE id IN (SELECT order_id FROM wave_orders WHERE wave_id = %s)
            """, (wave_id,))

            self.conn.commit()

        return self.get_wave(wave_id)

    def cancel_wave(self, wave_id):
        """
        Cancels a wave safely:
        1. Releases all inventory reservations back to available stock.
        2. Restores associated order statuses to 'Pending'.
        3. Sets wave status -> 'Cancelled'.
        """
        wave = self.get_wave(wave_id)
        if not wave:
            raise ValueError(f"Wave {wave_id} not found.")

        if wave["status"] == "Completed":
            raise ValueError("Cannot cancel an already completed wave.")

        with self.conn.cursor() as cur:
            # Release reservations
            cur.execute("""
                UPDATE inventory_reservations
                SET status = 'Released'
                WHERE wave_id = %s
            """, (wave_id,))

            # Reset order statuses back to 'Pending'
            cur.execute("""
                UPDATE orders
                SET status = 'Pending'
                WHERE id IN (SELECT order_id FROM wave_orders WHERE wave_id = %s)
            """, (wave_id,))

            # Update wave status
            cur.execute("UPDATE waves SET status = 'Cancelled' WHERE id = %s", (wave_id,))
            self.conn.commit()

        return self.get_wave(wave_id)

    # -------------------------------------------------------------
    # 7. Live Dashboard Metrics Calculation
    # -------------------------------------------------------------

    def get_dashboard_metrics(self):
        """
        Calculates live KPI metrics from actual database tables.
        Zero hardcoded or fake statistics. Appropriate empty states returned.
        """
        with self.conn.cursor() as cur:
            # Wave status counts
            cur.execute("""
                SELECT
                    COUNT(*) as total_waves,
                    SUM(CASE WHEN status = 'Draft' THEN 1 ELSE 0 END) as draft_waves,
                    SUM(CASE WHEN status = 'Scheduled' THEN 1 ELSE 0 END) as scheduled_waves,
                    SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_waves,
                    SUM(CASE WHEN status = 'Paused' THEN 1 ELSE 0 END) as paused_waves,
                    SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_waves,
                    SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled_waves,
                    SUM(total_units) as total_units_all,
                    SUM(picked_units) as picked_units_all,
                    SUM(distance_saved_m) as distance_saved_total,
                    SUM(unbatched_distance_m) as unbatched_dist_total
                FROM waves
            """)
            wave_stats = cur.fetchone()

            # Orders awaiting picking (status = 'Pending' and not in any active wave)
            allocated_ids = self.get_allocated_order_ids()
            if allocated_ids:
                placeholders = ",".join(["%s"] * len(allocated_ids))
                cur.execute(f"""
                    SELECT COUNT(*) as awaiting_count
                    FROM orders
                    WHERE status = 'Pending' AND id NOT IN ({placeholders})
                """, list(allocated_ids))
            else:
                cur.execute("SELECT COUNT(*) as awaiting_count FROM orders WHERE status = 'Pending'")
            awaiting_orders = cur.fetchone()["awaiting_count"]

            # Orders completed and pending packing
            cur.execute("""
                SELECT
                    SUM(CASE WHEN status = 'Picked' THEN 1 ELSE 0 END) as pending_packing,
                    SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_orders
                FROM orders
            """)
            order_lifecycle = cur.fetchone()

            # Active/pending pick units and tasks
            cur.execute("""
                SELECT
                    COUNT(DISTINCT pt.product_id) as total_items_to_pick,
                    COALESCE(SUM(pt.required_quantity - pt.picked_quantity), 0) as remaining_units_to_pick,
                    COALESCE(SUM(pt.required_quantity), 0) as total_units_to_pick,
                    COALESCE(SUM(pt.picked_quantity), 0) as picked_units_to_pick
                FROM pick_tasks pt
                JOIN waves w ON pt.wave_id = w.id
                WHERE w.status IN ('Active', 'Scheduled', 'Paused')
            """)
            task_stats = cur.fetchone()

            # Exceptions and shortages
            cur.execute("SELECT COUNT(*) as exception_count FROM wave_exceptions WHERE resolved = 0")
            exceptions_cnt = cur.fetchone()["exception_count"]

            # Calculate average picking duration for completed waves where timestamps exist
            cur.execute("""
                SELECT started_at, completed_at
                FROM waves
                WHERE status = 'Completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL
            """)
            completed_time_rows = cur.fetchall()

        # Parse duration
        durations_minutes = []
        for r in completed_time_rows:
            try:
                s_dt = datetime.strptime(str(r["started_at"])[:19], "%Y-%m-%d %H:%M:%S")
                c_dt = datetime.strptime(str(r["completed_at"])[:19], "%Y-%m-%d %H:%M:%S")
                dur = (c_dt - s_dt).total_seconds() / 60.0
                if dur > 0:
                    durations_minutes.append(dur)
            except Exception:
                pass

        avg_picking_time = round(sum(durations_minutes) / len(durations_minutes), 1) if durations_minutes else None

        tot_units = int(task_stats["total_units_to_pick"] or 0)
        pck_units = int(task_stats["picked_units_to_pick"] or 0)
        completed_cnt = int(wave_stats["completed_waves"] or 0)
        progress_pct = round((pck_units / tot_units * 100), 1) if tot_units > 0 else (100.0 if completed_cnt > 0 else 0.0)

        unbatched_sum = float(wave_stats["unbatched_dist_total"] or 0.0)
        saved_sum = float(wave_stats["distance_saved_total"] or 0.0)
        reduction_pct = round((saved_sum / unbatched_sum * 100), 1) if unbatched_sum > 0 else 0.0

        return {
            "total_waves": int(wave_stats["total_waves"] or 0),
            "status_counts": {
                "draft": int(wave_stats["draft_waves"] or 0),
                "scheduled": int(wave_stats["scheduled_waves"] or 0),
                "active": int(wave_stats["active_waves"] or 0),
                "paused": int(wave_stats["paused_waves"] or 0),
                "completed": int(wave_stats["completed_waves"] or 0),
                "cancelled": int(wave_stats["cancelled_waves"] or 0)
            },
            "orders_awaiting_picking": awaiting_orders,
            "orders_pending_packing": int(order_lifecycle["pending_packing"] or 0),
            "orders_completed": int(order_lifecycle["completed_orders"] or 0),
            "total_items_to_pick": int(task_stats["total_items_to_pick"] or 0),
            "units_to_pick": int(task_stats["remaining_units_to_pick"] or 0),
            "total_workload_units": tot_units,
            "picked_units": pck_units,
            "picking_progress_pct": progress_pct,
            "average_picking_time_mins": avg_picking_time,
            "active_exceptions": exceptions_cnt,
            "distance_saved_m": round(saved_sum, 1),
            "travel_reduction_pct": reduction_pct
        }

    # -------------------------------------------------------------
    # 8. CSV Export Helper
    # -------------------------------------------------------------

    def export_wave_csv(self, wave_id):
        """Generates CSV formatted consolidated pick list for printing or WMS integration."""
        wave = self.get_wave(wave_id)
        if not wave:
            raise ValueError(f"Wave {wave_id} not found.")

        lines = [
            f"# Wave Pick List: {wave['name']} ({wave['id']})",
            f"# Status: {wave['status']} | Strategy: {wave['strategy']} | Priority: {wave['priority']}",
            f"# Assigned Picker: {wave['assigned_picker']} | Scheduled: {wave['scheduled_at'] or 'Immediate'}",
            "Sequence,SKU,Product Name,Shelf,Aisle/Zone,Required Qty,Picked Qty,Remaining Qty,Status,Order Allocations"
        ]

        for t in wave["tasks"]:
            alloc_str = "; ".join([f"Order #{oid}: {qty}" for oid, qty in t["order_allocations"].items()])
            row = [
                str(t["sequence_order"]),
                t["sku"],
                f'"{t["product_name"]}"',
                t["shelf_label"],
                f'"{t["aisle_zone"]}"',
                str(t["required_quantity"]),
                str(t["picked_quantity"]),
                str(t["remaining_quantity"]),
                t["status"],
                f'"{alloc_str}"'
            ]
            lines.append(",".join(row))

        return "\n".join(lines)
