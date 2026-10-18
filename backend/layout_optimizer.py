"""
backend/layout_optimizer.py
Operations Research & Greedy Heuristic Slotting Optimization:
============================================================
Formulates warehouse slotting as a constrained Generalized Assignment Problem (GAP):
Minimize the total weighted travel demand:
    min Z = sum_{i in Products} sum_{j in Shelves} f_i * d_j * x_{ij}
Subject to:
    1. sum_{j in Shelves} x_{ij} = 1, for all i in Products (Every product must be assigned)
    2. sum_{i in Products} x_{ij} <= C_j, for all j in Shelves (Shelf capacity constraint)
    3. x_{ij} + x_{kj} <= 1, for all j, for (i, k) in IncompatibleCategories (Safety segregation)
    4. x_{ij} in {0, 1}

Heuristic Execution:
- Strategy 1: Velocity (Pareto ABC Analysis) - Sorts products descending by pick frequency f_i.
- Strategy 2: Cube-per-order index (COI) - Sorts products ascending by (volume / velocity).
- Sorts candidate storage shelves ascending by corridor distance to dispatch hub d_j.
- Corridor Routing: Same corridor = |Δy|. Different corridors = shorter of front (y=80) or back (y=430) cross-aisle route.
- Greedily assigns high-priority items to closest available shelves under constraints.
- Travel Index = Σ (weekly picks × 2 × hub distance) / 1000 (km/week).
"""

import json


def calculate_corridor_distance(shelf1, shelf2, front_y=80.0, back_y=430.0):
    """
    Computes distance between two shelves or locations:
    - Same corridor: |Δy|
    - Different corridors: min(front cross-aisle route, back cross-aisle route)
    """
    s1_x = getattr(shelf1, "x", 0)
    s1_y = getattr(shelf1, "y", 0)
    s2_x = getattr(shelf2, "x", 0)
    s2_y = getattr(shelf2, "y", 0)

    if s1_x == s2_x:
        return float(abs(s1_y - s2_y))

    # Aisle crossway distance: lateral travel + intra-aisle travel
    # Lateral distance factor scales grid coordinate differences to walkable meters
    lateral = abs(s1_x - s2_x) * 0.1
    front_route = abs(s1_y - front_y) + lateral + abs(s2_y - front_y)
    back_route = abs(s1_y - back_y) + lateral + abs(s2_y - back_y)
    return float(min(front_route, back_route))


class LayoutOptimizer:
    """
    Greedy Slotting Optimizer with Velocity (ABC) and Cube-per-Order Index (COI) strategies,
    corridor routing distance metrics, snapshot undo tracking, and multi-constraint enforcement.
    """

    def __init__(self):
        pass

    def optimize(self, products, shelves, strategy="velocity"):
        """
        Executes the greedy layout assignment algorithm.

        Args:
            products: list of Product objects (.id, .name, .category, .assigned_shelf_id, .pick_frequency, .volume)
            shelves: list of Shelf objects (.id, .distance_to_packing, .capacity, .x, .y)
            strategy: "velocity" (Pareto ABC picks/week desc) or "coi" (volume / velocity asc)

        Returns:
            assignments: list of old vs new shelf assignment comparison dictionaries.
            summary: aggregate operations research metrics (travel index, demand reduction, Pareto tiers, heatmap stats).
        """
        strategy = (strategy or "velocity").strip().lower()
        if strategy not in ("velocity", "coi"):
            strategy = "velocity"

        if not products or not shelves:
            empty_summary = {
                "strategy": strategy,
                "total_products": 0,
                "assigned_count": 0,
                "unassigned_count": 0,
                "moved_count": 0,
                "total_distance_saved_per_round": 0.0,
                "travel_index_before": 0.0,
                "travel_index_after": 0.0,
                "km_saved_per_week": 0.0,
                "reduction_pct": 0.0,
                "weighted_demand_before": 0.0,
                "weighted_demand_after": 0.0,
                "weighted_demand_reduction_pct": 0.0,
                "constraint_violations": 0,
                "shelf_heatmaps": []
            }
            return [], empty_summary

        # Step 1: Pareto ABC Tier Analysis based on pick velocity
        sorted_by_velocity = sorted(
            products,
            key=lambda p: float(p.pick_frequency or 0),
            reverse=True
        )
        total_volume = sum(float(p.pick_frequency or 0) for p in sorted_by_velocity)
        cum_volume = 0.0
        product_tiers = {}

        for p in sorted_by_velocity:
            freq = float(p.pick_frequency or 0)
            cum_volume += freq
            ratio = (cum_volume / total_volume) if total_volume > 0 else 0
            if ratio <= 0.80:
                product_tiers[p.id] = "A"
            elif ratio <= 0.95:
                product_tiers[p.id] = "B"
            else:
                product_tiers[p.id] = "C"

        # Step 2: Sort candidate products according to chosen strategy
        # - Velocity: Sort descending by weekly picks
        # - COI (Cube-per-order index): Sort ascending by volume / velocity
        if strategy == "coi":
            sorted_products = sorted(
                products,
                key=lambda p: (
                    float(getattr(p, "volume", 1.0) or 1.0) / max(float(p.pick_frequency or 0), 0.1),
                    -float(p.pick_frequency or 0)
                )
            )
        else:
            sorted_products = sorted_by_velocity

        # Step 3: Filter storage shelves (exclude Packing Station id=1) and sort ascending by distance to hub
        storage_shelves = [s for s in shelves if s.id != 1]
        sorted_shelves = sorted(
            storage_shelves,
            key=lambda s: float(s.distance_to_packing),
            reverse=False
        )

        shelf_dist_map = {s.id: float(s.distance_to_packing) for s in shelves}
        shelf_dist_map[None] = 0.0
        shelf_obj_map = {s.id: s for s in shelves}

        # Track shelf capacity and contents
        shelf_contents = {s.id: [] for s in sorted_shelves}
        shelf_capacities = {s.id: s.capacity for s in sorted_shelves}

        assignments = []
        unassigned = []

        # Step 4: Greedy heuristic assignment with constraint satisfaction
        for prod in sorted_products:
            assigned = False
            freq = float(prod.pick_frequency or 0)
            vol = float(getattr(prod, "volume", 1.0) or 1.0)
            coi = round(vol / max(freq, 0.1), 3)

            for shelf in sorted_shelves:
                s_id = shelf.id
                current_items = shelf_contents[s_id]

                # Constraint 1: Shelf capacity limit (|items| < C_j)
                if len(current_items) >= shelf_capacities[s_id]:
                    continue

                # Constraint 2: Strict category segregation (Fragile vs Heavy)
                existing_categories = {item.category for item in current_items}
                if prod.category == "Fragile" and "Heavy" in existing_categories:
                    continue
                if prod.category == "Heavy" and "Fragile" in existing_categories:
                    continue

                # Feasible assignment found
                shelf_contents[s_id].append(prod)
                old_shelf = prod.assigned_shelf_id
                old_dist = shelf_dist_map.get(old_shelf, 0.0)
                new_dist = shelf.distance_to_packing

                # Weekly travel distances in km: weekly picks * 2 * hub distance / 1000
                weekly_travel_before = round((freq * 2.0 * old_dist) / 1000.0, 4)
                weekly_travel_after = round((freq * 2.0 * new_dist) / 1000.0, 4)
                weekly_effect_km = round(weekly_travel_before - weekly_travel_after, 4)

                assignments.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "sku": f"SKU-{prod.id:04d}",
                    "category": prod.category,
                    "tier": product_tiers.get(prod.id, "C"),
                    "pick_frequency": round(freq, 1),
                    "volume": round(vol, 2),
                    "coi": coi,
                    "old_shelf_id": old_shelf,
                    "new_shelf_id": s_id,
                    "old_distance": round(old_dist, 1),
                    "new_distance": round(new_dist, 1),
                    "distance_diff": round(old_dist - new_dist, 1),
                    "weekly_travel_before_km": weekly_travel_before,
                    "weekly_travel_after_km": weekly_travel_after,
                    "weekly_effect_km": weekly_effect_km,
                    "is_moved": (old_shelf != s_id)
                })
                assigned = True
                break

            if not assigned:
                unassigned.append(prod)

        # Step 5: Sort planned moves table by biggest gain first (weekly_effect_km descending)
        assignments.sort(key=lambda a: (a["weekly_effect_km"], a["distance_diff"]), reverse=True)

        # Step 6: Travel Index calculation (km/week)
        # Travel index = Σ (weekly picks × 2 × hub-to-shelf distance) / 1000
        travel_index_before = sum(a["weekly_travel_before_km"] for a in assignments)
        travel_index_after = sum(a["weekly_travel_after_km"] for a in assignments)
        km_saved_per_week = round(max(0.0, travel_index_before - travel_index_after), 3)

        reduction_pct = (
            round(((travel_index_before - travel_index_after) / travel_index_before) * 100.0, 1)
            if travel_index_before > 0 else 0.0
        )

        moved_count = sum(1 for a in assignments if a["is_moved"])
        distance_saved_per_round = sum(a["distance_diff"] for a in assignments if a["distance_diff"] > 0)

        # Step 7: Heatmap aggregations for Before vs After floor maps
        # Aggregate weekly picks and SKU count per shelf for current and proposed
        current_shelf_agg = {s.id: {"picks": 0.0, "count": 0, "skus": []} for s in storage_shelves}
        for p in products:
            s_id = p.assigned_shelf_id
            if s_id in current_shelf_agg:
                current_shelf_agg[s_id]["picks"] += float(p.pick_frequency or 0)
                current_shelf_agg[s_id]["count"] += 1
                current_shelf_agg[s_id]["skus"].append(p.name)

        proposed_shelf_agg = {s.id: {"picks": 0.0, "count": 0, "skus": []} for s in storage_shelves}
        for a in assignments:
            s_id = a["new_shelf_id"]
            if s_id in proposed_shelf_agg:
                proposed_shelf_agg[s_id]["picks"] += a["pick_frequency"]
                proposed_shelf_agg[s_id]["count"] += 1
                proposed_shelf_agg[s_id]["skus"].append(a["product_name"])

        shelf_heatmaps = []
        for s in storage_shelves:
            c_info = current_shelf_agg.get(s.id, {"picks": 0.0, "count": 0, "skus": []})
            p_info = proposed_shelf_agg.get(s.id, {"picks": 0.0, "count": 0, "skus": []})
            shelf_heatmaps.append({
                "shelf_id": s.id,
                "x": s.x,
                "y": s.y,
                "capacity": s.capacity,
                "distance_to_packing": round(s.distance_to_packing, 1),
                "current_picks": round(c_info["picks"], 1),
                "current_count": c_info["count"],
                "current_skus": c_info["skus"],
                "proposed_picks": round(p_info["picks"], 1),
                "proposed_count": p_info["count"],
                "proposed_skus": p_info["skus"]
            })

        summary = {
            "strategy": strategy,
            "total_products": len(products),
            "assigned_count": len(assignments),
            "unassigned_count": len(unassigned),
            "moved_count": moved_count,
            "travel_index_before": round(travel_index_before, 2),
            "travel_index_after": round(travel_index_after, 2),
            "km_saved_per_week": km_saved_per_week,
            "reduction_pct": reduction_pct,
            "total_distance_saved_per_round": round(distance_saved_per_round, 1),
            "weighted_demand_before": round(travel_index_before * 1000.0 / 2.0, 1),
            "weighted_demand_after": round(travel_index_after * 1000.0 / 2.0, 1),
            "weighted_demand_reduction_pct": reduction_pct,
            "constraint_violations": 0,
            "shelf_heatmaps": shelf_heatmaps
        }

        return assignments, summary

    def apply(self, conn, assignments, user_email="admin@warehouse.io", strategy="velocity", summary=None):
        """
        Commits optimized shelf assignments transactionally to the database.
        1. Captures snapshot of previous assignments in layout_snapshots for undo support.
        2. Updates `products.assigned_shelf_id`.
        3. Refreshes `shelves.current_load`.
        4. Writes audit entry into auth_audit_logs.
        """
        cursor = conn.cursor()

        # Step 1: Capture previous state of affected products
        product_ids = [item["product_id"] if isinstance(item, dict) else item.product_id for item in assignments]
        if not product_ids:
            cursor.close()
            return False, "No assignments to apply."

        format_strings = ",".join(["%s"] * len(product_ids))
        cursor.execute(f"SELECT id, assigned_shelf_id FROM products WHERE id IN ({format_strings})", tuple(product_ids))
        old_rows = cursor.fetchall()
        old_shelf_map = {r["id"] if isinstance(r, dict) else r[0]: r["assigned_shelf_id"] if isinstance(r, dict) else r[1] for r in old_rows}

        snapshot_payload = []
        for item in assignments:
            p_id = item["product_id"] if isinstance(item, dict) else item.product_id
            new_shelf = item.get("new_shelf_id") if isinstance(item, dict) else getattr(item, "new_shelf_id", None)
            if new_shelf is None and isinstance(item, dict):
                new_shelf = item.get("shelf_id")
            old_shelf = old_shelf_map.get(p_id)
            snapshot_payload.append({
                "product_id": p_id,
                "old_shelf_id": old_shelf,
                "new_shelf_id": new_shelf
            })

        travel_before = float(summary.get("travel_index_before", 0.0) if summary else 0.0)
        travel_after = float(summary.get("travel_index_after", 0.0) if summary else 0.0)
        reduction_pct = float(summary.get("reduction_pct", 0.0) if summary else 0.0)

        # Mark any previous active snapshots as superseded so undo always targets the latest layout
        cursor.execute("UPDATE layout_snapshots SET status = 'superseded' WHERE status = 'applied'")

        # Store snapshot
        cursor.execute("""
            INSERT INTO layout_snapshots 
            (strategy, assignments_json, travel_index_before, travel_index_after, reduction_pct, user_email, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'applied')
        """, (
            strategy or "velocity",
            json.dumps(snapshot_payload),
            travel_before,
            travel_after,
            reduction_pct,
            user_email or "admin@warehouse.io"
        ))
        snapshot_id = cursor.lastrowid

        # Step 2: Apply new assignments to products
        for item in snapshot_payload:
            cursor.execute(
                "UPDATE products SET assigned_shelf_id = %s WHERE id = %s",
                (item["new_shelf_id"], item["product_id"])
            )

        # Step 3: Recalculate shelf loads
        cursor.execute("""
            UPDATE shelves
            SET current_load = (
                SELECT COUNT(*) FROM products WHERE products.assigned_shelf_id = shelves.id
            )
        """)

        # Step 4: Write audit log
        try:
            cursor.execute("""
                INSERT INTO auth_audit_logs (user_id, email, action, ip_address, status, details)
                VALUES (NULL, %s, 'LAYOUT_OPTIMIZE', '127.0.0.1', 'SUCCESS', %s)
            """, (
                user_email or "admin@warehouse.io",
                f"Applied {strategy.upper()} layout: {len(assignments)} SKUs re-slotted, {reduction_pct}% reduction (Snapshot #{snapshot_id})"
            ))
        except Exception as audit_err:
            print(f"[Audit Log Warning] {audit_err}")

        conn.commit()
        cursor.close()
        return True, snapshot_id

    def undo(self, conn, user_email="admin@warehouse.io"):
        """
        Restores product assignments from the most recent active layout snapshot.
        Marks snapshot as reverted and adds a warning audit log entry.
        """
        cursor = conn.cursor()

        # Find latest applied snapshot
        cursor.execute("""
            SELECT id, strategy, assignments_json, reduction_pct, created_at 
            FROM layout_snapshots 
            WHERE status = 'applied' 
            ORDER BY id DESC LIMIT 1
        """)
        snapshot = cursor.fetchone()
        if not snapshot:
            cursor.close()
            return False, "No active layout snapshot available to undo."

        snapshot_id = snapshot["id"] if isinstance(snapshot, dict) else snapshot[0]
        raw_json = snapshot["assignments_json"] if isinstance(snapshot, dict) else snapshot[2]
        reduction = snapshot["reduction_pct"] if isinstance(snapshot, dict) else snapshot[3]

        assignments = json.loads(raw_json)
        restored_count = 0

        for item in assignments:
            p_id = item["product_id"]
            old_shelf = item["old_shelf_id"]
            cursor.execute(
                "UPDATE products SET assigned_shelf_id = %s WHERE id = %s",
                (old_shelf, p_id)
            )
            restored_count += 1

        # Refresh shelf current_load
        cursor.execute("""
            UPDATE shelves
            SET current_load = (
                SELECT COUNT(*) FROM products WHERE products.assigned_shelf_id = shelves.id
            )
        """)

        # Mark snapshot as reverted
        cursor.execute("UPDATE layout_snapshots SET status = 'reverted' WHERE id = %s", (snapshot_id,))

        # Write audit log with WARNING status
        try:
            cursor.execute("""
                INSERT INTO auth_audit_logs (user_id, email, action, ip_address, status, details)
                VALUES (NULL, %s, 'LAYOUT_UNDO', '127.0.0.1', 'WARNING', %s)
            """, (
                user_email or "admin@warehouse.io",
                f"Undid layout snapshot #{snapshot_id}: reverted {restored_count} product shelf assignments"
            ))
        except Exception as audit_err:
            print(f"[Audit Log Warning] {audit_err}")

        conn.commit()
        cursor.close()
        return True, {
            "snapshot_id": snapshot_id,
            "restored_count": restored_count,
            "message": f"Successfully reverted {restored_count} SKUs to previous shelf assignments."
        }
