"""
backend/layout_optimizer.py
Greedy Layout Optimization Algorithm:
1. Sort products by pick frequency (total units sold from sales) descending.
2. Sort storage shelves by distance to packing station ascending.
3. Greedily assign highest-frequency products to the closest available shelves.
4. Enforce constraints:
   - Capacity constraint: Never exceed shelf capacity limit.
   - Categorical constraint: Fragile and Heavy categories must not be placed on the same shelf.
"""

class LayoutOptimizer:
    def __init__(self):
        pass

    def optimize(self, products, shelves):
        """
        Executes the greedy layout assignment.
        products: list of Product objects (with .id, .name, .category, .assigned_shelf_id, .pick_frequency)
        shelves: list of Shelf objects (with .id, .distance_to_packing, .capacity, etc.)
        
        Returns:
            assignments: list of assignment diff objects (old vs new)
            summary: aggregate optimization metrics
        """
        # Step 1: Sort products by pick frequency descending (fast-moving items first)
        sorted_products = sorted(
            products, 
            key=lambda p: p.pick_frequency, 
            reverse=True
        )

        # Step 2: Filter out packing area (id=1) and sort storage shelves by distance ascending
        storage_shelves = [s for s in shelves if s.id != 1]
        sorted_shelves = sorted(
            storage_shelves, 
            key=lambda s: s.distance_to_packing, 
            reverse=False
        )

        # Quick lookup for shelf distance
        shelf_distance_map = {s.id: s.distance_to_packing for s in shelves}
        shelf_distance_map[None] = 0.0

        # Track products placed on each shelf during greedy assignment
        shelf_contents = {s.id: [] for s in sorted_shelves}
        shelf_capacities = {s.id: s.capacity for s in sorted_shelves}

        assignments = []
        unassigned = []

        # Step 3 & 4: Greedily place each product into the closest compatible shelf
        for prod in sorted_products:
            assigned = False

            for shelf in sorted_shelves:
                s_id = shelf.id
                current_items = shelf_contents[s_id]

                # Constraint 1: Shelf capacity limit
                if len(current_items) >= shelf_capacities[s_id]:
                    continue

                # Constraint 2: Segregation of Fragile and Heavy categories
                existing_categories = {p.category for p in current_items}
                if prod.category == "Fragile" and "Heavy" in existing_categories:
                    continue
                if prod.category == "Heavy" and "Fragile" in existing_categories:
                    continue

                # Shelf is valid! Assign product
                shelf_contents[s_id].append(prod)
                old_shelf = prod.assigned_shelf_id
                old_dist = shelf_distance_map.get(old_shelf, 0.0)
                new_dist = shelf.distance_to_packing

                assignments.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "category": prod.category,
                    "pick_frequency": prod.pick_frequency,
                    "old_shelf_id": old_shelf,
                    "new_shelf_id": s_id,
                    "old_distance": old_dist,
                    "new_distance": new_dist,
                    "distance_diff": round(old_dist - new_dist, 1)
                })
                assigned = True
                break

            if not assigned:
                unassigned.append(prod)

        # Calculate metrics
        moved_count = sum(1 for a in assignments if a["old_shelf_id"] != a["new_shelf_id"])
        distance_saved = sum(a["distance_diff"] for a in assignments if a["distance_diff"] > 0)

        summary = {
            "total_products": len(products),
            "assigned_count": len(assignments),
            "unassigned_count": len(unassigned),
            "moved_count": moved_count,
            "total_distance_saved_per_round": round(distance_saved, 1)
        }

        return assignments, summary

    def apply(self, conn, assignments):
        """
        Commits the optimized layout assignments to MySQL.
        Updates products table and recalculates current_load on shelves.
        """
        cursor = conn.cursor()
        
        # 1. Update product shelf assignments
        for item in assignments:
            cursor.execute(
                "UPDATE products SET assigned_shelf_id = %s WHERE id = %s",
                (item["new_shelf_id"], item["product_id"])
            )

        # 2. Recalculate current_load for each shelf
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
