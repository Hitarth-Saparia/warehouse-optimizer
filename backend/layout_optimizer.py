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
- Implements Pareto ABC Analysis: Sorts products descending by pick frequency f_i.
- Sorts candidate storage shelves ascending by corridor distance to dispatch hub d_j.
- Greedily assigns high-velocity (Tier A) items to closest available shelves under constraints.
"""


class LayoutOptimizer:
    """
    Greedy Slotting Optimizer with Pareto velocity ranking and multi-constraint enforcement.
    """

    def __init__(self):
        pass

    def optimize(self, products, shelves):
        """
        Executes the greedy layout assignment algorithm.

        Args:
            products: list of Product objects (.id, .name, .category, .assigned_shelf_id, .pick_frequency)
            shelves: list of Shelf objects (.id, .distance_to_packing, .capacity)

        Returns:
            assignments: list of old vs new shelf assignment comparison dictionaries.
            summary: aggregate operations research metrics (total demand reduction, Pareto tiers).
        """
        if not products or not shelves:
            return [], {
                "total_products": 0,
                "assigned_count": 0,
                "unassigned_count": 0,
                "moved_count": 0,
                "total_distance_saved_per_round": 0.0,
                "weighted_demand_before": 0.0,
                "weighted_demand_after": 0.0,
                "weighted_demand_reduction_pct": 0.0
            }

        # Step 1: Pareto ABC Analysis - Sort products descending by pick frequency
        sorted_products = sorted(
            products, 
            key=lambda p: float(p.pick_frequency or 0), 
            reverse=True
        )

        total_volume = sum(float(p.pick_frequency or 0) for p in sorted_products)
        cum_volume = 0.0
        product_tiers = {}

        for p in sorted_products:
            freq = float(p.pick_frequency or 0)
            cum_volume += freq
            ratio = (cum_volume / total_volume) if total_volume > 0 else 0
            if ratio <= 0.80:
                product_tiers[p.id] = "A"
            elif ratio <= 0.95:
                product_tiers[p.id] = "B"
            else:
                product_tiers[p.id] = "C"

        # Step 2: Filter storage shelves (exclude Packing Station id=1) and sort by distance ascending
        storage_shelves = [s for s in shelves if s.id != 1]
        sorted_shelves = sorted(
            storage_shelves, 
            key=lambda s: s.distance_to_packing, 
            reverse=False
        )

        # Lookup mapping for shelf distances
        shelf_dist_map = {s.id: float(s.distance_to_packing) for s in shelves}
        shelf_dist_map[None] = 0.0

        # State tracking for shelf capacity & assigned items
        shelf_contents = {s.id: [] for s in sorted_shelves}
        shelf_capacities = {s.id: s.capacity for s in sorted_shelves}

        assignments = []
        unassigned = []

        weighted_demand_before = 0.0
        weighted_demand_after = 0.0

        # Step 3: Greedy heuristic assignment with constraint satisfaction
        for prod in sorted_products:
            assigned = False
            freq = float(prod.pick_frequency or 0)

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

                weighted_demand_before += (freq * old_dist)
                weighted_demand_after += (freq * new_dist)

                assignments.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "category": prod.category,
                    "tier": product_tiers.get(prod.id, "C"),
                    "pick_frequency": freq,
                    "old_shelf_id": old_shelf,
                    "new_shelf_id": s_id,
                    "old_distance": round(old_dist, 1),
                    "new_distance": round(new_dist, 1),
                    "distance_diff": round(old_dist - new_dist, 1)
                })
                assigned = True
                break

            if not assigned:
                unassigned.append(prod)

        # Step 4: Compute aggregated Operations Research metrics
        moved_count = sum(1 for a in assignments if a["old_shelf_id"] != a["new_shelf_id"])
        distance_saved_per_round = sum(a["distance_diff"] for a in assignments if a["distance_diff"] > 0)

        weighted_saved = max(0.0, weighted_demand_before - weighted_demand_after)
        reduction_pct = round((weighted_saved / weighted_demand_before * 100), 1) if weighted_demand_before > 0 else 0.0

        summary = {
            "total_products": len(products),
            "assigned_count": len(assignments),
            "unassigned_count": len(unassigned),
            "moved_count": moved_count,
            "total_distance_saved_per_round": round(distance_saved_per_round, 1),
            "weighted_demand_before": round(weighted_demand_before, 1),
            "weighted_demand_after": round(weighted_demand_after, 1),
            "weighted_demand_reduction_pct": reduction_pct
        }

        return assignments, summary

    def apply(self, conn, assignments):
        """
        Commits optimized shelf assignments transactionally to MySQL.
        Updates `products.assigned_shelf_id` and recalculates `shelves.current_load`.
        """
        cursor = conn.cursor()

        # Update each product's shelf location
        for item in assignments:
            cursor.execute(
                "UPDATE products SET assigned_shelf_id = %s WHERE id = %s",
                (item["new_shelf_id"], item["product_id"])
            )

        # Reset and refresh current_load aggregations on shelves
        cursor.execute("UPDATE shelves SET current_load = 0")
        cursor.execute("""
            UPDATE shelves s
            JOIN (
                SELECT assigned_shelf_id, COUNT(*) as cnt 
                FROM products 
                WHERE assigned_shelf_id IS NOT NULL 
                GROUP BY assigned_shelf_id
            ) p ON s.id = p.assigned_shelf_id
            SET s.current_load = p.cnt
        """)

        conn.commit()
        cursor.close()
        return True
