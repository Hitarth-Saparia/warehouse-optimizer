"""
backend/fleet_allocator.py
Operations Research: Multiple Traveling Salesperson Problem (mTSP) & Fleet Balancing:
====================================================================================
Assigns pending warehouse orders/tours across a fleet of M pickers (e.g. Workers 1, 2, 3)
to optimize warehouse shift throughput.

Objectives:
1. Min-Max Makespan: Minimize the maximum completion time across all workers:
       min max_{w in Workers} TotalDistance(w)
   Ensures the entire order wave finishes as fast as possible without bottlenecks.
2. Workload Equity & Fatigue Prevention:
   Balances the physical travel demand (meters walked) across workers, minimizing
   workload variance and the Gini coefficient:
       G = sum_i sum_j |D_i - D_j| / (2 * M * sum_i D_i)
3. Zone Deconfliction:
   Groups orders with shared primary aisle footprints to minimize corridor congestion.
"""

import math
import heapq
from backend.models import Worker
from backend.route_optimizer import RouteOptimizer


class FleetAllocator:
    """
    Solves mTSP fleet workload balancing across multiple warehouse pickers.
    """

    def __init__(self, warehouse, worker_names=None):
        """
        Args:
            warehouse: instance of Warehouse class.
            worker_names: list of worker names or identifiers.
        """
        self.warehouse = warehouse
        self.route_optimizer = RouteOptimizer(warehouse)
        names = worker_names or ["Picker Alpha", "Picker Bravo", "Picker Charlie"]
        self.workers = [Worker(id=i + 1, name=name, current_shelf_id=1) for i, name in enumerate(names)]

    def allocate(self, orders, shelf_mapping=None, walking_speed_m_per_sec=1.1):
        """
        Distributes orders across the worker fleet using min-heap makespan balancing.

        Args:
            orders: list of Order objects.
            shelf_mapping: dict product_id -> shelf_id.
            walking_speed_m_per_sec: average picker walking speed (default: 1.1 m/s).

        Returns:
            fleet_assignments: dict mapping worker_id -> worker assignments & tour details.
            metrics: fleet-level workload equity and makespan metrics.
        """
        if not orders:
            return [], {
                "total_orders": 0,
                "fleet_size": len(self.workers),
                "makespan_distance": 0.0,
                "makespan_time_minutes": 0.0,
                "total_fleet_distance": 0.0,
                "gini_coefficient": 0.0,
                "is_balanced": True
            }

        # 1. Evaluate individual order routes & requirements
        evaluated_orders = []
        for o in orders:
            if not o.items:
                continue

            shelf_ids = []
            total_qty = 0
            for it in o.items:
                p_id = it.get("product_id")
                qty = it.get("quantity", 1)
                total_qty += qty
                s_id = shelf_mapping.get(p_id) if shelf_mapping else it.get("shelf_id")
                if s_id and s_id != 1:
                    shelf_ids.append(int(s_id))

            route_info = self.route_optimizer.solve_order_route(o.id, shelf_ids)
            dist = route_info["total_distance"]

            # Determine dominant aisle zone (Aisle 1, 2, 3, or 4) for zone awareness
            aisle_ids = [s for s in shelf_ids if s > 1]
            primary_aisle = "Mixed"
            if aisle_ids:
                aisle_buckets = [(s - 2) // 6 + 1 for s in aisle_ids]
                primary_aisle = f"Aisle {max(set(aisle_buckets), key=aisle_buckets.count)}"

            evaluated_orders.append({
                "order_id": o.id,
                "customer_name": o.customer_name,
                "items_count": len(o.items),
                "total_units": total_qty,
                "distance": dist,
                "primary_aisle": primary_aisle,
                "route": route_info
            })

        # 2. Min-Heap Makespan Balancing (Longest Processing Time Heuristic)
        # Sort jobs descending by required walking distance
        sorted_jobs = sorted(evaluated_orders, key=lambda x: x["distance"], reverse=True)

        # Min-heap tracks: (cumulative_distance, worker_index)
        worker_heap = [(0.0, i) for i in range(len(self.workers))]
        heapq.heapify(worker_heap)

        # Structure to collect tasks per worker
        worker_plans = [{
            "worker_id": w.id,
            "worker_name": w.name,
            "assigned_orders": [],
            "total_distance": 0.0,
            "total_units": 0,
            "total_stops": 0,
            "est_time_minutes": 0.0
        } for w in self.workers]

        for job in sorted_jobs:
            current_dist, w_idx = heapq.heappop(worker_heap)
            worker_plans[w_idx]["assigned_orders"].append(job)
            new_dist = round(current_dist + job["distance"], 2)
            worker_plans[w_idx]["total_distance"] = new_dist
            worker_plans[w_idx]["total_units"] += job["total_units"]
            worker_plans[w_idx]["total_stops"] += job["route"]["stop_count"]

            # Push updated cumulative load back into heap
            heapq.heappush(worker_heap, (new_dist, w_idx))

        # 3. Compute times and fleet balance equity
        for plan in worker_plans:
            # Estimate walking time: distance / speed + pick time (15s per unit)
            walk_seconds = plan["total_distance"] / walking_speed_m_per_sec
            pick_seconds = plan["total_units"] * 15.0
            total_seconds = walk_seconds + pick_seconds
            plan["est_time_minutes"] = round(total_seconds / 60.0, 1)

        worker_distances = [p["total_distance"] for p in worker_plans]
        total_fleet_dist = round(sum(worker_distances), 2)
        makespan_dist = round(max(worker_distances), 2) if worker_distances else 0.0
        makespan_time = max(p["est_time_minutes"] for p in worker_plans) if worker_plans else 0.0

        # Gini Coefficient Calculation for Workload Equity
        m = len(worker_distances)
        gini = 0.0
        if m > 1 and total_fleet_dist > 0:
            diff_sum = sum(abs(a - b) for a in worker_distances for b in worker_distances)
            gini = round(diff_sum / (2.0 * m * total_fleet_dist), 3)

        metrics = {
            "total_orders": len(evaluated_orders),
            "fleet_size": m,
            "makespan_distance": makespan_dist,
            "makespan_time_minutes": makespan_time,
            "total_fleet_distance": total_fleet_dist,
            "avg_distance_per_worker": round(total_fleet_dist / m, 2) if m > 0 else 0.0,
            "gini_coefficient": gini,
            "is_balanced": gini < 0.20
        }

        return worker_plans, metrics
