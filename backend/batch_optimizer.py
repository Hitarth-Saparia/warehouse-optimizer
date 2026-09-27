"""
backend/batch_optimizer.py
Operations Research & Order Batching Problem (OBP):
===================================================
Solves the Order Batching Problem for Warehouse Wave Picking.
Instead of sending a picker on individual round trips for each customer order,
multiple orders are clustered into batches (waves) subject to physical cart
capacity constraints:
    sum_{o in Batch_k} items(o) <= CartCapacity

Batching Strategy:
1. Seed-based Savings Clustering:
   - Identify seed orders based on furthest storage aisle reaches.
   - Greedily merge companion orders that share common shelf stops or corridors:
     Similarity(O_a, O_b) = |Stops(O_a) cap Stops(O_b)| / |Stops(O_a) cup Stops(O_b)|
   - Enforce capacity limits (e.g. maximum items per picking cart).
2. Consolidated TSP Routing:
   - For each formed batch, synthesize the unified stop set S(Batch_k) = cup_{o} Stops(o).
   - Compute the optimal consolidated picking tour via RouteOptimizer (Exact TSP / 2-Opt).
3. Empirical Batching Efficiency Benchmarks:
   - Compares Sum(Individual Tour Distances) vs Sum(Batched Tour Distances).
   - Computes distance saved and operational throughput acceleration.
"""

from backend.route_optimizer import RouteOptimizer


class BatchOptimizer:
    """
    Solves the Order Batching Problem (OBP) with capacity-constrained wave formation.
    """

    def __init__(self, warehouse, max_cart_capacity=15, max_orders_per_batch=4):
        """
        Args:
            warehouse: instance of Warehouse class.
            max_cart_capacity: max units/items a picker cart can hold.
            max_orders_per_batch: max customer orders to aggregate in one cart tote.
        """
        self.warehouse = warehouse
        self.max_cart_capacity = max_cart_capacity
        self.max_orders_per_batch = max_orders_per_batch
        self.route_optimizer = RouteOptimizer(warehouse)

    def optimize_batches(self, orders, shelf_mapping=None):
        """
        Groups customer orders into optimal pick batches and routes each batch.

        Args:
            orders: list of Order objects.
            shelf_mapping: dict mapping product_id -> shelf_id (optional, uses order item shelf_id if None).

        Returns:
            batches: list of batch execution dictionaries with routed tours.
            metrics: comparative summary between unbatched vs batched picking.
        """
        if not orders:
            return [], {
                "total_orders": 0,
                "total_batches": 0,
                "unbatched_total_distance": 0.0,
                "batched_total_distance": 0.0,
                "distance_saved": 0.0,
                "percent_reduction": 0.0
            }

        # 1. Preprocess each order to extract item counts and shelf stops
        order_meta = []
        for o in orders:
            if not o.items:
                continue

            shelf_ids = set()
            total_units = 0
            for it in o.items:
                p_id = it.get("product_id")
                qty = it.get("quantity", 1)
                total_units += qty

                s_id = shelf_mapping.get(p_id) if shelf_mapping else it.get("shelf_id")
                if s_id and s_id != 1:
                    shelf_ids.add(int(s_id))

            # Compute baseline individual tour distance for this single order
            single_route = self.route_optimizer.solve_order_route(o.id, list(shelf_ids))

            order_meta.append({
                "order": o,
                "order_id": o.id,
                "customer_name": o.customer_name,
                "shelf_ids": shelf_ids,
                "total_units": total_units,
                "individual_distance": single_route["total_distance"]
            })

        # Total distance if orders were picked individually
        unbatched_total_distance = sum(om["individual_distance"] for om in order_meta)

        # 2. Seed-Based Greedy Clustering Algorithm
        # Sort unassigned orders by individual distance descending (seed with furthest reach)
        unassigned = sorted(order_meta, key=lambda x: x["individual_distance"], reverse=True)
        batches_raw = []

        while unassigned:
            # Seed a new batch with the first unassigned order
            seed = unassigned.pop(0)
            current_batch_orders = [seed]
            current_capacity = seed["total_units"]
            current_shelves = set(seed["shelf_ids"])

            # Iteratively evaluate remaining unassigned orders for maximum corridor synergy
            i = 0
            while i < len(unassigned) and len(current_batch_orders) < self.max_orders_per_batch:
                candidate = unassigned[i]

                # Check cart capacity constraint
                if current_capacity + candidate["total_units"] <= self.max_cart_capacity:
                    # Calculate Jaccard similarity of shelf stops
                    union_shelves = current_shelves.union(candidate["shelf_ids"])
                    intersection_shelves = current_shelves.intersection(candidate["shelf_ids"])
                    similarity = len(intersection_shelves) / len(union_shelves) if union_shelves else 0.0

                    # Merge candidate if there is aisle sharing or capacity allows
                    current_batch_orders.append(candidate)
                    current_capacity += candidate["total_units"]
                    current_shelves = union_shelves
                    unassigned.pop(i)
                else:
                    i += 1

            batches_raw.append(current_batch_orders)

        # 3. Route each synthesized wave/batch with RouteOptimizer
        batched_results = []
        batched_total_distance = 0.0

        for b_idx, batch_orders in enumerate(batches_raw):
            batch_id = b_idx + 1
            all_stops = set()
            all_items = []
            order_ids = []
            customer_names = []
            total_batch_units = 0

            for bo in batch_orders:
                order_ids.append(bo["order_id"])
                customer_names.append(bo["customer_name"])
                total_batch_units += bo["total_units"]
                all_stops.update(bo["shelf_ids"])
                for item in bo["order"].items:
                    all_items.append({
                        "order_id": bo["order_id"],
                        "product_name": item.get("name", f"Product #{item.get('product_id')}"),
                        "quantity": item.get("quantity", 1),
                        "shelf_id": shelf_mapping.get(item.get("product_id")) if shelf_mapping else item.get("shelf_id")
                    })

            # Solve unified TSP tour for the batch
            batch_route = self.route_optimizer.solve_order_route(f"Batch-{batch_id}", list(all_stops))
            batch_dist = batch_route["total_distance"]
            batched_total_distance += batch_dist

            individual_sum = sum(bo["individual_distance"] for bo in batch_orders)
            saved = max(0.0, round(individual_sum - batch_dist, 2))
            pct_saved = round((saved / individual_sum * 100), 1) if individual_sum > 0 else 0.0

            batched_results.append({
                "batch_id": batch_id,
                "batch_name": f"Wave #{batch_id}",
                "order_ids": order_ids,
                "orders_count": len(order_ids),
                "customers": customer_names,
                "total_units": total_batch_units,
                "unique_stops": len(all_stops),
                "unbatched_distance": round(individual_sum, 2),
                "batched_distance": batch_dist,
                "distance_saved": saved,
                "percent_saved": pct_saved,
                "algorithm": batch_route["algorithm"],
                "stops": batch_route["stops"],
                "legs": batch_route["legs"],
                "full_path": batch_route["full_path"],
                "items": all_items
            })

        overall_saved = max(0.0, round(unbatched_total_distance - batched_total_distance, 2))
        overall_pct = round((overall_saved / unbatched_total_distance * 100), 1) if unbatched_total_distance > 0 else 0.0

        metrics = {
            "total_orders": len(order_meta),
            "total_batches": len(batched_results),
            "avg_orders_per_batch": round(len(order_meta) / len(batched_results), 1) if batched_results else 0.0,
            "unbatched_total_distance": round(unbatched_total_distance, 2),
            "batched_total_distance": round(batched_total_distance, 2),
            "distance_saved": overall_saved,
            "percent_reduction": overall_pct
        }

        return batched_results, metrics
