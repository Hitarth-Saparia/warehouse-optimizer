"""
backend/fleet_balancer.py
Operations Research & Vehicle Fleet Balancing Engine:
=====================================================
1. Multi-Criteria Vehicle Load Balancing & Bin Packing (Best-Fit Decreasing + Zone Affinity)
2. Warehouse-Level Fleet Demand vs Capacity Analysis & Inter-Warehouse Reallocation Recommendations
3. Multi-Stop Route Sequencing & Vehicle Operating Cost Optimization (Before vs After Comparison)
4. Two-Phase Execution: Propose Optimization -> Review -> Confirm & Apply Changes Transactionally
"""

import math
import json
from datetime import datetime
from backend.db import get_db
from backend.models import Vehicle, WarehouseLocation, Order, BalancingRun, VehicleAssignment


# Geographical Coordinate System for Logistics Hubs and Delivery Zones
WAREHOUSE_COORDINATES = {
    "WH-01": {"name": "Central Distribution Center", "x": 0.0, "y": 0.0},
    "WH-02": {"name": "North Metro Logistics Hub", "x": 15.0, "y": 22.0},
    "WH-03": {"name": "West River Freight Depot", "x": -18.0, "y": 10.0}
}

ZONE_COORDINATES = {
    "Zone A - Downtown": {"x": 3.5, "y": 4.0, "hub": "WH-01"},
    "Zone B - East Industrial": {"x": 8.0, "y": 2.5, "hub": "WH-01"},
    "Zone C - North Suburbs": {"x": 18.0, "y": 26.0, "hub": "WH-02"},
    "Zone D - Airport Logistics": {"x": 12.0, "y": 30.0, "hub": "WH-02"},
    "Zone E - West Harbor": {"x": -22.0, "y": 12.0, "hub": "WH-03"},
    "Zone F - Tech Corridor": {"x": -15.0, "y": 16.0, "hub": "WH-03"}
}

DEFAULT_ZONE = "Zone A - Downtown"
CIRCUITY_FACTOR = 1.30  # Road circuity factor converts Euclidean to realistic transit distance


def calculate_distance_km(x1, y1, x2, y2):
    """Calculates estimated road distance in kilometers using Euclidean distance with circuity factor."""
    euclidean = math.hypot(x1 - x2, y1 - y2)
    return round(max(2.0, euclidean * CIRCUITY_FACTOR), 2)


def get_zone_coords(zone_name):
    """Returns (x, y) coordinates for a destination zone."""
    if zone_name in ZONE_COORDINATES:
        return ZONE_COORDINATES[zone_name]["x"], ZONE_COORDINATES[zone_name]["y"]
    # Fallback default
    return 3.5, 4.0


def get_warehouse_coords(wh_id):
    """Returns (x, y) coordinates for a warehouse hub."""
    if wh_id in WAREHOUSE_COORDINATES:
        return WAREHOUSE_COORDINATES[wh_id]["x"], WAREHOUSE_COORDINATES[wh_id]["y"]
    return 0.0, 0.0


class FleetBalancer:
    """
    Core algorithmic engine for Vehicle Fleet Balancing and Multi-Warehouse Optimization.
    """

    def __init__(self, conn=None):
        self._external_conn = conn

    def _get_connection(self):
        if self._external_conn:
            return self._external_conn, False
        return get_db(), True

    def fetch_vehicles(self):
        """Fetches all vehicles from the database."""
        conn, should_close = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, vehicle_type, max_capacity, current_load,
                           location, status, cost_per_km, fixed_cost, created_at
                    FROM vehicles
                    ORDER BY id ASC
                """)
                rows = cur.fetchall()
                return [Vehicle(
                    id=r["id"],
                    name=r["name"],
                    vehicle_type=r["vehicle_type"],
                    max_capacity=r["max_capacity"],
                    current_load=r["current_load"],
                    location=r["location"],
                    status=r["status"],
                    cost_per_km=r["cost_per_km"],
                    fixed_cost=r["fixed_cost"],
                    created_at=r.get("created_at")
                ) for r in rows]
        finally:
            if should_close:
                conn.close()

    def fetch_warehouses(self):
        """Fetches all warehouse hubs."""
        conn, should_close = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, location, coord_x, coord_y, service_zones
                    FROM warehouses
                    ORDER BY id ASC
                """)
                rows = cur.fetchall()
                warehouses = []
                for r in rows:
                    raw_zones = r.get("service_zones", "")
                    zones = [z.strip() for z in raw_zones.split(",") if z.strip()] if isinstance(raw_zones, str) else []
                    warehouses.append(WarehouseLocation(
                        id=r["id"],
                        name=r["name"],
                        location=r["location"],
                        coord_x=r.get("coord_x", 0.0),
                        coord_y=r.get("coord_y", 0.0),
                        service_zones=zones
                    ))
                return warehouses
        finally:
            if should_close:
                conn.close()

    def fetch_orders(self, only_pending=True):
        """Fetches orders with all fleet properties."""
        conn, should_close = self._get_connection()
        try:
            from backend.app import fetch_all_orders
            all_orders = fetch_all_orders(conn)
            if only_pending:
                return [o for o in all_orders if o.status == "Pending"]
            return all_orders
        finally:
            if should_close:
                conn.close()

    def get_dashboard_summary(self):
        """
        Computes real-time executive dashboard KPIs from active project data.
        """
        vehicles = self.fetch_vehicles()
        orders = self.fetch_orders(only_pending=False)
        warehouses = self.fetch_warehouses()

        pending_orders = [o for o in orders if o.status == "Pending"]
        completed_orders = [o for o in orders if o.status == "Completed"]
        assigned_orders = [o for o in pending_orders if o.assigned_vehicle_id]
        unassigned_orders = [o for o in pending_orders if not o.assigned_vehicle_id]

        total_vehicles = len(vehicles)
        available_vehicles = [v for v in vehicles if v.is_available]
        active_vehicles = [v for v in available_vehicles if v.current_load > 0]
        idle_vehicles = [v for v in available_vehicles if v.current_load <= 0]
        in_transit_vehicles = [v for v in vehicles if v.status == "In Transit"]
        maintenance_vehicles = [v for v in vehicles if v.status == "Maintenance"]

        total_fleet_capacity = sum(v.max_capacity for v in available_vehicles)
        total_assigned_load = sum(v.current_load for v in available_vehicles)
        fleet_utilization_pct = round((total_assigned_load / total_fleet_capacity * 100.0), 1) if total_fleet_capacity > 0 else 0.0

        underutilized_vehicles = [v for v in active_vehicles if v.utilization_pct < 50.0]
        overloaded_vehicles = [v for v in vehicles if v.current_load > v.max_capacity]

        # Warehouse demand summaries
        warehouse_summaries = []
        imbalance_alerts = []

        for wh in warehouses:
            wh_vehicles = [v for v in vehicles if v.location == wh.id]
            wh_available = [v for v in wh_vehicles if v.is_available]
            wh_capacity = sum(v.max_capacity for v in wh_available)
            wh_assigned_load = sum(v.current_load for v in wh_available)
            wh_pending_orders = [o for o in pending_orders if o.warehouse_id == wh.id]
            wh_demand_weight = sum(o.weight for o in wh_pending_orders)
            wh_unassigned = [o for o in wh_pending_orders if not o.assigned_vehicle_id]

            util_pct = round((wh_assigned_load / wh_capacity * 100.0), 1) if wh_capacity > 0 else 0.0
            demand_ratio = round((wh_demand_weight / wh_capacity * 100.0), 1) if wh_capacity > 0 else 999.0

            # Imbalance classification
            if wh_capacity == 0 and wh_demand_weight > 0:
                wh_status = "Critical Deficit"
                imbalance_alerts.append({
                    "severity": "danger",
                    "title": f"{wh.name} Fleet Deficit",
                    "message": f"Zero available vehicles stationed at {wh.id} with {round(wh_demand_weight, 1)} kg pending demand."
                })
            elif demand_ratio > 95.0 or len(wh_unassigned) > 0 and len(wh_available) > 0:
                wh_status = "Deficit"
                imbalance_alerts.append({
                    "severity": "warning",
                    "title": f"{wh.name} Capacity Strain",
                    "message": f"Demand reaches {demand_ratio}% of fleet capacity ({round(wh_demand_weight, 1)} kg / {round(wh_capacity, 1)} kg)."
                })
            elif demand_ratio < 35.0 and len(wh_available) >= 2:
                wh_status = "Surplus"
                imbalance_alerts.append({
                    "severity": "info",
                    "title": f"{wh.name} Excess Fleet Capacity",
                    "message": f"Low demand ({demand_ratio}%). {len(wh_available)} vehicles available for potential regional rebalancing."
                })
            else:
                wh_status = "Balanced"

            warehouse_summaries.append({
                "warehouse_id": wh.id,
                "name": wh.name,
                "location": wh.location,
                "total_vehicles": len(wh_vehicles),
                "available_vehicles": len(wh_available),
                "fleet_capacity_kg": wh_capacity,
                "assigned_load_kg": round(wh_assigned_load, 1),
                "utilization_pct": util_pct,
                "pending_orders_count": len(wh_pending_orders),
                "pending_demand_kg": round(wh_demand_weight, 1),
                "demand_capacity_ratio": demand_ratio,
                "unassigned_orders_count": len(wh_unassigned),
                "status": wh_status
            })

        # Calculate estimated operational costs based on current assignments
        current_cost, current_dist = self._estimate_fleet_cost_and_distance(available_vehicles, assigned_orders)

        # Baseline cost (if unoptimized individual dispatches were used)
        baseline_cost, baseline_dist = self._estimate_baseline_cost(pending_orders)
        potential_savings = max(0.0, round(baseline_cost - current_cost, 2))
        savings_pct = round((potential_savings / baseline_cost * 100.0), 1) if baseline_cost > 0 else 0.0

        return {
            "metrics": {
                "total_vehicles": total_vehicles,
                "available_vehicles": len(available_vehicles),
                "active_vehicles": len(active_vehicles),
                "idle_vehicles": len(idle_vehicles),
                "in_transit_vehicles": len(in_transit_vehicles),
                "maintenance_vehicles": len(maintenance_vehicles),
                "total_fleet_capacity": total_fleet_capacity,
                "total_assigned_load": round(total_assigned_load, 1),
                "fleet_utilization_pct": fleet_utilization_pct,
                "total_orders": len(orders),
                "pending_orders": len(pending_orders),
                "assigned_orders": len(assigned_orders),
                "unassigned_orders": len(unassigned_orders),
                "completed_orders": len(completed_orders),
                "underutilized_vehicles_count": len(underutilized_vehicles),
                "overloaded_vehicles_count": len(overloaded_vehicles),
                "estimated_operating_cost": current_cost,
                "baseline_operating_cost": baseline_cost,
                "potential_savings": potential_savings,
                "savings_pct": savings_pct,
                "estimated_distance_km": current_dist,
                "baseline_distance_km": baseline_dist
            },
            "warehouse_summaries": warehouse_summaries,
            "imbalance_alerts": imbalance_alerts
        }

    def _estimate_baseline_cost(self, orders):
        """
        Calculates baseline dispatch distance & cost (naive/unoptimized round trips).
        """
        if not orders:
            return 0.0, 0.0

        total_dist = 0.0
        total_cost = 0.0
        # Benchmark medium delivery vehicle: $1.75/km + $25 dispatch base
        base_fixed = 25.0
        base_rate = 1.75

        for o in orders:
            wh_coords = get_warehouse_coords(o.warehouse_id)
            z_coords = get_zone_coords(o.destination_zone)
            # Naive uncombined round-trip distance
            one_way = calculate_distance_km(wh_coords[0], wh_coords[1], z_coords[0], z_coords[1])
            round_trip = round(one_way * 2.0, 2)
            total_dist += round_trip
            total_cost += base_fixed + (round_trip * base_rate)

        return round(total_cost, 2), round(total_dist, 2)

    def _estimate_fleet_cost_and_distance(self, vehicles, assigned_orders):
        """
        Computes clustered multi-stop route distances and operating costs for assigned vehicles.
        """
        if not vehicles or not assigned_orders:
            return 0.0, 0.0

        orders_by_vehicle = {}
        for o in assigned_orders:
            v_id = o.assigned_vehicle_id
            if v_id:
                if v_id not in orders_by_vehicle:
                    orders_by_vehicle[v_id] = []
                orders_by_vehicle[v_id].append(o)

        total_cost = 0.0
        total_dist = 0.0

        for v in vehicles:
            v_orders = orders_by_vehicle.get(v.id, [])
            if not v_orders:
                continue

            wh_coords = get_warehouse_coords(v.location)
            # Unique zones to visit
            unique_zones = list({o.destination_zone for o in v_orders})

            # Solve multi-stop TSP route order using nearest-neighbor heuristic
            stops = [wh_coords]
            for z in unique_zones:
                stops.append(get_zone_coords(z))

            # Tour: Warehouse -> Stop 1 -> Stop 2 -> ... -> Return to Warehouse
            tour_dist = self._solve_nearest_neighbor_tour(stops)
            # Add small intra-zone delivery distance for multiple stops in same zone
            intra_zone_stops = max(0, len(v_orders) - len(unique_zones))
            tour_dist += round(intra_zone_stops * 2.8, 2)

            v_cost = v.fixed_cost + (tour_dist * v.cost_per_km)
            total_dist += tour_dist
            total_cost += v_cost

        return round(total_cost, 2), round(total_dist, 2)

    def _solve_nearest_neighbor_tour(self, coords_list):
        """
        Computes closed-loop TSP tour distance visiting all coordinate stops starting and ending at index 0.
        """
        if len(coords_list) <= 1:
            return 0.0
        if len(coords_list) == 2:
            d = calculate_distance_km(coords_list[0][0], coords_list[0][1], coords_list[1][0], coords_list[1][1])
            return round(d * 2.0, 2)

        unvisited = list(range(1, len(coords_list)))
        current_idx = 0
        total_dist = 0.0

        while unvisited:
            best_next = None
            best_d = float("inf")
            c_x, c_y = coords_list[current_idx]

            for cand in unvisited:
                n_x, n_y = coords_list[cand]
                d = calculate_distance_km(c_x, c_y, n_x, n_y)
                if d < best_d:
                    best_d = d
                    best_next = cand

            total_dist += best_d
            current_idx = best_next
            unvisited.remove(best_next)

        # Return to origin warehouse
        last_x, last_y = coords_list[current_idx]
        orig_x, orig_y = coords_list[0]
        total_dist += calculate_distance_km(last_x, last_y, orig_x, orig_y)

        return round(total_dist, 2)

    def run_balancing(self, strategy="best_fit_zone"):
        """
        Executes Fleet Load Balancing and Warehouse Demand Reallocation Optimization.
        Generates proposed allocation, metrics, cost comparisons, and recommendations.
        Persists a 'Proposed' balancing run in the database for user review.
        """
        vehicles = self.fetch_vehicles()
        orders = self.fetch_orders(only_pending=True)
        warehouses = self.fetch_warehouses()

        available_vehicles = [v for v in vehicles if v.is_available]

        # Reset in-memory load copies for simulation
        sim_vehicles = {v.id: {
            "vehicle": v,
            "assigned_orders": [],
            "current_load": 0.0,
            "max_capacity": v.max_capacity,
            "location": v.location
        } for v in available_vehicles}

        # Priority weights: Urgent: 4, High: 3, Standard: 2, Low: 1
        prio_weights = {"urgent": 4, "high": 3, "standard": 2, "low": 1}

        # Sort orders: Highest priority first, then deadline, then weight descending (Best-Fit Decreasing)
        def sort_key(o):
            p_val = prio_weights.get(o.priority.lower(), 2)
            return (-p_val, o.deadline, -o.weight)

        sorted_orders = sorted(orders, key=sort_key)

        assigned_plan = []
        unassigned_orders = []

        # 1. Order Allocation Phase
        for o in sorted_orders:
            # Find candidate available vehicles stationed at the order's originating warehouse
            wh_cands = [sv for sv in sim_vehicles.values() if sv["location"] == o.warehouse_id]

            # Filter candidates that can fit this order
            fitting_cands = [sv for sv in wh_cands if (sv["current_load"] + o.weight) <= sv["max_capacity"]]

            if not fitting_cands:
                # If cannot fit at origin warehouse, record as unassigned
                unassigned_orders.append({
                    "order_id": o.id,
                    "customer_name": o.customer_name,
                    "weight": o.weight,
                    "destination_zone": o.destination_zone,
                    "priority": o.priority,
                    "warehouse_id": o.warehouse_id,
                    "reason": f"Insufficient fleet capacity at {o.warehouse_id} (weight: {o.weight} kg)"
                })
                continue

            # Multi-criteria vehicle scoring:
            # - Zone affinity: +50 pts if vehicle already delivers to this destination zone
            # - Best-Fit: +30 * (1 - leftover/capacity) tightly packs vehicles
            # - Operating efficiency: +20 * (1 / cost_per_km)
            scored_cands = []
            for sv in fitting_cands:
                veh = sv["vehicle"]
                new_load = sv["current_load"] + o.weight
                remaining = sv["max_capacity"] - new_load

                zone_bonus = 0.0
                if any(assigned["destination_zone"] == o.destination_zone for assigned in sv["assigned_orders"]):
                    zone_bonus = 50.0

                pack_score = 30.0 * (1.0 - (remaining / max(1.0, sv["max_capacity"])))
                cost_score = 20.0 * (1.0 / max(0.5, veh.cost_per_km))

                score = zone_bonus + pack_score + cost_score
                scored_cands.append((score, sv))

            scored_cands.sort(key=lambda x: x[0], reverse=True)
            chosen_sv = scored_cands[0][1]

            # Commit assignment in simulation
            order_summary = {
                "order_id": o.id,
                "customer_name": o.customer_name,
                "weight": o.weight,
                "destination_zone": o.destination_zone,
                "priority": o.priority,
                "deadline": o.deadline,
                "warehouse_id": o.warehouse_id
            }
            chosen_sv["assigned_orders"].append(order_summary)
            chosen_sv["current_load"] = round(chosen_sv["current_load"] + o.weight, 1)

            assigned_plan.append({
                "order_id": o.id,
                "customer_name": o.customer_name,
                "weight": o.weight,
                "destination_zone": o.destination_zone,
                "priority": o.priority,
                "deadline": o.deadline,
                "warehouse_id": o.warehouse_id,
                "vehicle_id": chosen_sv["vehicle"].id,
                "vehicle_name": chosen_sv["vehicle"].name,
                "vehicle_type": chosen_sv["vehicle"].vehicle_type
            })

        # 2. Warehouse Demand Balancing & Inter-Warehouse Reallocation Recommendations
        recommendations = []
        rec_counter = 1

        for wh in warehouses:
            wh_unassigned = [uo for uo in unassigned_orders if uo["warehouse_id"] == wh.id]
            wh_unassigned_weight = sum(uo["weight"] for uo in wh_unassigned)

            if wh_unassigned_weight > 0:
                # Find surplus warehouses that have idle or lightly loaded vehicles
                surplus_candidates = []
                for other_wh in warehouses:
                    if other_wh.id == wh.id:
                        continue

                    other_svs = [sv for sv in sim_vehicles.values() if sv["location"] == other_wh.id]
                    idle_svs = [sv for sv in other_svs if sv["current_load"] <= 0.0]
                    for idle_sv in idle_svs:
                        surplus_candidates.append((other_wh, idle_sv))

                if surplus_candidates:
                    # Choose candidate vehicle whose capacity best fits the deficit
                    surplus_candidates.sort(key=lambda item: abs(item[1]["max_capacity"] - wh_unassigned_weight))
                    source_wh, cand_sv = surplus_candidates[0]
                    veh = cand_sv["vehicle"]

                    trans_dist = calculate_distance_km(
                        get_warehouse_coords(source_wh.id)[0], get_warehouse_coords(source_wh.id)[1],
                        get_warehouse_coords(wh.id)[0], get_warehouse_coords(wh.id)[1]
                    )
                    trans_cost = round(trans_dist * veh.cost_per_km, 2)

                    recommendations.append({
                        "id": f"REC-0{rec_counter}",
                        "type": "VEHICLE_REALLOCATION",
                        "vehicle_id": veh.id,
                        "vehicle_name": veh.name,
                        "vehicle_type": veh.vehicle_type,
                        "from_warehouse_id": source_wh.id,
                        "from_warehouse_name": source_wh.name,
                        "to_warehouse_id": wh.id,
                        "to_warehouse_name": wh.name,
                        "transfer_distance_km": trans_dist,
                        "transfer_cost": trans_cost,
                        "unmet_demand_covered_kg": min(veh.max_capacity, wh_unassigned_weight),
                        "reason": f"Warehouse {wh.id} has {round(wh_unassigned_weight, 1)} kg unassigned demand with 0 available capacity. {source_wh.name} has idle vehicle {veh.name} ({round(veh.max_capacity, 1)} kg capacity). Reallocation balances demand."
                    })
                    rec_counter += 1

        # 3. Post-Balancing Fleet Metrics & Route Evaluation
        proposed_vehicle_allocations = []
        total_balanced_load = 0.0
        total_balanced_capacity = sum(v.max_capacity for v in available_vehicles)

        for sv in sim_vehicles.values():
            veh = sv["vehicle"]
            load = sv["current_load"]
            util_pct = round((load / veh.max_capacity * 100.0), 1) if veh.max_capacity > 0 else 0.0
            total_balanced_load += load

            # Route calculation for this vehicle
            v_orders = sv["assigned_orders"]
            unique_zones = list({o["destination_zone"] for o in v_orders})
            wh_coords = get_warehouse_coords(sv["location"])

            stops = [wh_coords] + [get_zone_coords(z) for z in unique_zones]
            tour_dist = self._solve_nearest_neighbor_tour(stops)
            intra_zone_stops = max(0, len(v_orders) - len(unique_zones))
            tour_dist += round(intra_zone_stops * 2.8, 2)

            tour_cost = round(veh.fixed_cost + (tour_dist * veh.cost_per_km), 2) if v_orders else 0.0
            # Estimate transit time: ~40 km/h average city transit + 15 mins per order stop
            transit_hours = tour_dist / 40.0
            service_hours = (len(v_orders) * 15.0) / 60.0
            est_time_mins = round((transit_hours + service_hours) * 60.0, 1) if v_orders else 0.0

            proposed_vehicle_allocations.append({
                "vehicle_id": veh.id,
                "name": veh.name,
                "vehicle_type": veh.vehicle_type,
                "max_capacity": veh.max_capacity,
                "assigned_load": load,
                "available_capacity": round(max(0.0, veh.max_capacity - load), 1),
                "utilization_pct": util_pct,
                "location": sv["location"],
                "orders_count": len(v_orders),
                "assigned_orders": v_orders,
                "zones_covered": unique_zones,
                "tour_distance_km": tour_dist,
                "tour_cost": tour_cost,
                "est_time_mins": est_time_mins,
                "status": "Overloaded" if load > veh.max_capacity else ("Optimal" if util_pct >= 60.0 else ("Underutilized" if load > 0 else "Idle"))
            })

        overall_proposed_util = round((total_balanced_load / total_balanced_capacity * 100.0), 1) if total_balanced_capacity > 0 else 0.0

        # Current vs Proposed comparisons
        cost_before, dist_before = self._estimate_baseline_cost(orders)
        cost_after = round(sum(pva["tour_cost"] for pva in proposed_vehicle_allocations), 2)
        dist_after = round(sum(pva["tour_distance_km"] for pva in proposed_vehicle_allocations), 2)

        cost_savings = max(0.0, round(cost_before - cost_after, 2))
        savings_pct = round((cost_savings / cost_before * 100.0), 1) if cost_before > 0 else 0.0
        dist_savings = max(0.0, round(dist_before - dist_after, 2))

        # Store balancing run record as 'Proposed'
        conn, should_close = self._get_connection()
        run_id = None
        try:
            with conn.cursor() as cur:
                summary_data = {
                    "assigned_plan": assigned_plan,
                    "unassigned_orders": unassigned_orders,
                    "proposed_vehicle_allocations": proposed_vehicle_allocations,
                    "recommendations": recommendations,
                    "metrics": {
                        "total_vehicles": len(vehicles),
                        "available_vehicles": len(available_vehicles),
                        "orders_assigned": len(assigned_plan),
                        "orders_unassigned": len(unassigned_orders),
                        "total_demand_kg": round(sum(o.weight for o in orders), 1),
                        "allocated_load_kg": round(total_balanced_load, 1),
                        "fleet_utilization_pct": overall_proposed_util,
                        "cost_before": cost_before,
                        "cost_after": cost_after,
                        "cost_savings": cost_savings,
                        "savings_pct": savings_pct,
                        "distance_before_km": dist_before,
                        "distance_after_km": dist_after,
                        "distance_savings_km": dist_savings
                    }
                }
                summary_json_str = json.dumps(summary_data)

                cur.execute("""
                    INSERT INTO balancing_runs
                    (status, total_vehicles, assigned_orders_count, unassigned_orders_count,
                     fleet_utilization_pct, cost_before, cost_after, cost_savings,
                     distance_before, distance_after, summary_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    "Proposed",
                    len(available_vehicles),
                    len(assigned_plan),
                    len(unassigned_orders),
                    overall_proposed_util,
                    cost_before,
                    cost_after,
                    cost_savings,
                    dist_before,
                    dist_after,
                    summary_json_str
                ))
                run_id = cur.lastrowid
                conn.commit()
        finally:
            if should_close:
                conn.close()

        return {
            "run_id": run_id,
            "status": "Proposed",
            "created_at": datetime.now().isoformat(),
            "comparison": {
                "cost_before": cost_before,
                "cost_after": cost_after,
                "cost_savings": cost_savings,
                "savings_pct": savings_pct,
                "distance_before_km": dist_before,
                "distance_after_km": dist_after,
                "distance_savings_km": dist_savings,
                "utilization_pct": overall_proposed_util
            },
            "proposed_vehicle_allocations": proposed_vehicle_allocations,
            "assigned_plan": assigned_plan,
            "unassigned_orders": unassigned_orders,
            "recommendations": recommendations,
            "available_vehicles_count": len(available_vehicles),
            "orders_assigned_count": len(assigned_plan),
            "orders_unassigned_count": len(unassigned_orders)
        }

    def apply_balancing(self, run_id):
        """
        Applies a proposed Fleet Balancing run to the persistent database.
        Atomically updates orders, vehicle current loads, and records vehicle assignments.
        Guarantees protection of completed orders and prevents duplicate/conflicting assignments.
        """
        conn, should_close = self._get_connection()
        try:
            with conn.cursor() as cur:
                # 1. Fetch proposed run
                cur.execute("SELECT id, status, summary_json FROM balancing_runs WHERE id = %s", (run_id,))
                run_row = cur.fetchone()
                if not run_row:
                    raise ValueError(f"Balancing run #{run_id} not found.")

                if run_row["status"] == "Applied":
                    return {"status": "success", "message": f"Run #{run_id} is already applied."}

                summary = json.loads(run_row["summary_json"]) if run_row.get("summary_json") else {}
                assigned_plan = summary.get("assigned_plan", [])

                if not assigned_plan:
                    raise ValueError("Proposed run contains no vehicle order assignments to apply.")

                # 2. Reset existing pending order assignments and vehicle loads
                cur.execute("SELECT id, status FROM orders WHERE id IN (%s)" %
                            ",".join(str(p["order_id"]) for p in assigned_plan))
                current_orders = {r["id"]: r["status"] for r in cur.fetchall()}

                # Reset loads on active vehicles
                cur.execute("UPDATE vehicles SET current_load = 0.0")

                # Track vehicle new loads
                vehicle_new_loads = {}
                applied_count = 0

                # 3. Apply proposed assignments safely
                for item in assigned_plan:
                    o_id = item["order_id"]
                    v_id = item["vehicle_id"]
                    wt = float(item.get("weight", 0.0))

                    # Completed order protection
                    if current_orders.get(o_id) == "Completed":
                        continue

                    # Update order assigned vehicle
                    cur.execute(
                        "UPDATE orders SET assigned_vehicle_id = %s WHERE id = %s AND status = 'Pending'",
                        (v_id, o_id)
                    )

                    # Record assignment entry
                    cur.execute("""
                        INSERT INTO vehicle_assignments (vehicle_id, order_id, run_id, status)
                        VALUES (%s, %s, %s, 'Assigned')
                    """, (v_id, o_id, run_id))

                    vehicle_new_loads[v_id] = vehicle_new_loads.get(v_id, 0.0) + wt
                    applied_count += 1

                # 4. Update vehicle assigned loads in database
                for v_id, load in vehicle_new_loads.items():
                    cur.execute(
                        "UPDATE vehicles SET current_load = %s WHERE id = %s",
                        (round(load, 1), v_id)
                    )

                # 5. Mark balancing run as 'Applied'
                cur.execute("UPDATE balancing_runs SET status = 'Applied' WHERE id = %s", (run_id,))
                conn.commit()

                return {
                    "status": "success",
                    "run_id": run_id,
                    "orders_applied": applied_count,
                    "vehicles_updated": len(vehicle_new_loads),
                    "message": f"Successfully applied fleet balancing run #{run_id} ({applied_count} orders assigned)."
                }
        except Exception:
            conn.rollback()
            raise
        finally:
            if should_close:
                conn.close()

    def discard_balancing(self, run_id):
        """Discards a proposed balancing run."""
        conn, should_close = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, status FROM balancing_runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Balancing run #{run_id} not found.")

                cur.execute("UPDATE balancing_runs SET status = 'Discarded' WHERE id = %s", (run_id,))
                conn.commit()
                return {"status": "success", "run_id": run_id, "message": f"Run #{run_id} discarded."}
        finally:
            if should_close:
                conn.close()

    def get_runs_history(self, limit=20):
        """Retrieves history of balancing runs."""
        conn, should_close = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, status, total_vehicles, assigned_orders_count, unassigned_orders_count,
                           fleet_utilization_pct, cost_before, cost_after, cost_savings,
                           distance_before, distance_after, created_at
                    FROM balancing_runs
                    ORDER BY id DESC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
                runs = []
                for r in rows:
                    savings = float(r.get("cost_savings", 0.0))
                    c_before = float(r.get("cost_before", 0.0))
                    savings_pct = round((savings / c_before * 100.0), 1) if c_before > 0 else 0.0
                    runs.append({
                        "id": r["id"],
                        "status": r["status"],
                        "total_vehicles": r["total_vehicles"],
                        "assigned_orders_count": r["assigned_orders_count"],
                        "unassigned_orders_count": r["unassigned_orders_count"],
                        "fleet_utilization_pct": float(r["fleet_utilization_pct"]),
                        "cost_before": c_before,
                        "cost_after": float(r.get("cost_after", 0.0)),
                        "cost_savings": savings,
                        "savings_pct": savings_pct,
                        "distance_before": float(r.get("distance_before", 0.0)),
                        "distance_after": float(r.get("distance_after", 0.0)),
                        "created_at": str(r.get("created_at"))
                    })
                return runs
        finally:
            if should_close:
                conn.close()
