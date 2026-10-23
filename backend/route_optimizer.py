"""
backend/route_optimizer.py
Combinatorial Optimization & Traveling Salesperson Problem (TSP):
================================================================
Models order picking as the Metric Traveling Salesperson Problem (Metric TSP):
Given customer order stops S subset V and origin Hub v_0 (Shelf 1), find a
Hamiltonian cycle C = (v_0, v_pi(1), v_pi(2), ..., v_pi(k), v_0) that minimizes:
    Cost(C) = sum_{i=0}^k delta(v_pi(i), v_pi(i+1))

Algorithm Selection Strategy:
1. Exact Solvers for Small Instances (k < 8):
   - Branch-and-bound permutation enumeration with early cost bounding.
   - Guaranteed global mathematical optimum. Time: O(k!).
2. Metaheuristic Solvers for Large Instances (k >= 8):
   - Greedy Nearest-Neighbor Initialization: O(k^2).
   - 2-Opt Local Search Optimization: Iterative edge swap heuristic that
     eliminates tour crossings and optimizes local metric paths. Time: O(k^2) per iteration.
"""

import itertools
import time


class RouteOptimizer:
    """
    Solves TSP picking tours across warehouse graph corridors.
    Provides exact branch-and-bound, Held-Karp DP, greedy nearest-neighbor,
    2-opt local search refinement, and standard warehouse S-Shape routing.
    """

    def __init__(self, warehouse):
        """
        Args:
            warehouse: instance of Warehouse class providing shortest path corridors.
        """
        self.warehouse = warehouse
        self.packing_shelf_id = 1
        self.default_walking_speed_mps = 1.3
        self.default_seconds_per_pick = 35.0

    def solve_order_route(self, order_id, shelf_ids, algorithm_choice="auto"):
        """
        Computes optimal picking tour starting at Shelf 1, visiting all required
        shelf_ids, and returning to Shelf 1.

        Args:
            order_id: integer identifier of the order.
            shelf_ids: list of shelf IDs to visit.
            algorithm_choice: 'auto', 'exact', 'nearest_neighbor', 'nn_2opt', 's_shape'.

        Returns:
            Structured dictionary with tour sequence, legs, full path, baseline comparison,
            and algorithm computational metrics.
        """
        start_time = time.perf_counter()

        # Preserve order of arrival for baseline calculation
        ordered_unique_stops = []
        seen = set()
        for s in shelf_ids:
            if s is not None:
                s_int = int(s)
                if s_int != self.packing_shelf_id and s_int not in seen:
                    seen.add(s_int)
                    ordered_unique_stops.append(s_int)

        unique_stops = list(ordered_unique_stops)
        k = len(unique_stops)

        if k == 0:
            calc_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "order_id": order_id,
                "algorithm": "Trivial (No Pick Stops)",
                "complexity": "O(1)",
                "calculation_time_ms": calc_time_ms,
                "stop_count": 0,
                "stops": [self.packing_shelf_id],
                "full_path": [self.packing_shelf_id],
                "total_distance": 0.0,
                "baseline_distance": 0.0,
                "distance_saved_m": 0.0,
                "percent_saved": 0.0,
                "estimated_time_seconds": 0.0,
                "baseline_time_seconds": 0.0,
                "time_saved_seconds": 0.0,
                "legs": [],
                "unreachable": False,
                "unreachable_stops": []
            }

        # Build pairwise distance cache between all candidate tour nodes
        tour_nodes = [self.packing_shelf_id] + unique_stops
        dist_cache = {}
        unreachable_stops = set()

        for u in tour_nodes:
            for v in tour_nodes:
                if (u, v) not in dist_cache:
                    d = self.warehouse.get_distance(u, v)
                    dist_cache[(u, v)] = d
                    dist_cache[(v, u)] = d
                    if d == float('inf'):
                        if u != self.packing_shelf_id:
                            unreachable_stops.add(u)
                        if v != self.packing_shelf_id:
                            unreachable_stops.add(v)

        if unreachable_stops:
            calc_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "order_id": order_id,
                "algorithm": "Unreachable Destination",
                "complexity": "N/A",
                "calculation_time_ms": calc_time_ms,
                "stop_count": k,
                "stops": [self.packing_shelf_id],
                "full_path": [self.packing_shelf_id],
                "total_distance": 0.0,
                "baseline_distance": 0.0,
                "distance_saved_m": 0.0,
                "percent_saved": 0.0,
                "estimated_time_seconds": 0.0,
                "baseline_time_seconds": 0.0,
                "time_saved_seconds": 0.0,
                "legs": [],
                "unreachable": True,
                "unreachable_stops": sorted(list(unreachable_stops)),
                "error_message": f"Shelf stop(s) {', '.join(f'S-{s:02d}' for s in sorted(unreachable_stops))} cannot be reached from the Packing Dock due to corridor blockages or graph disconnections."
            }

        # Baseline: Sequential pick list order as submitted
        baseline_tour = [self.packing_shelf_id] + unique_stops + [self.packing_shelf_id]
        baseline_distance = round(sum(dist_cache[(baseline_tour[i], baseline_tour[i + 1])] for i in range(len(baseline_tour) - 1)), 2)

        algo_lower = str(algorithm_choice).lower().strip()

        # Algorithm Selection
        if algo_lower == "exact" or (algo_lower == "auto" and k <= 12):
            if k < 8:
                algorithm = "Branch-and-Bound (Exact TSP)"
                complexity = f"Exact optimum · O({k}!)"
                ordered_tour = self._solve_brute_force(unique_stops, dist_cache)
            else:
                algorithm = "Held-Karp DP (Exact TSP)"
                complexity = f"Exact optimum · O({k}²·2^{k})"
                ordered_tour = self._solve_held_karp(unique_stops, dist_cache)
        elif algo_lower == "nearest_neighbor":
            algorithm = "Nearest-Neighbor (Greedy TSP)"
            complexity = f"Greedy heuristic · O({k}²)"
            ordered_tour = self._solve_nearest_neighbor(unique_stops, dist_cache)
        elif algo_lower == "s_shape":
            algorithm = "S-Shape (Serpentine)"
            complexity = f"Corridor traversal · O({k} log {k})"
            ordered_tour = self._solve_s_shape(unique_stops, dist_cache)
        else: # "nn_2opt" or "auto" for k > 12
            algorithm = "Nearest-Neighbor + 2-Opt (Local Search)"
            complexity = f"Heuristic approximation · O({k}²)"
            raw_tour = self._solve_nearest_neighbor(unique_stops, dist_cache)
            ordered_tour = self._apply_2opt(raw_tour, dist_cache)


        # Build physical node-by-node corridor traversals and legs
        legs = []
        full_path = [self.packing_shelf_id]
        total_distance = 0.0

        for i in range(len(ordered_tour) - 1):
            u = ordered_tour[i]
            v = ordered_tour[i + 1]
            leg_dist, leg_path = self.warehouse.dijkstra(u, v)
            total_distance += leg_dist
            legs.append({
                "from_shelf": u,
                "to_shelf": v,
                "distance": round(leg_dist, 2),
                "path": leg_path
            })
            if len(leg_path) > 1:
                full_path.extend(leg_path[1:])

        total_distance = round(total_distance, 2)
        calc_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Baseline savings & estimated picking times
        distance_saved = round(max(0.0, baseline_distance - total_distance), 2)
        pct_saved = round((distance_saved / baseline_distance * 100.0), 1) if baseline_distance > 0 else 0.0

        # Estimated picking time: distance / walking_speed + (stops * seconds_per_pick)
        estimated_time = round((total_distance / self.default_walking_speed_mps) + (k * self.default_seconds_per_pick), 1)
        baseline_time = round((baseline_distance / self.default_walking_speed_mps) + (k * self.default_seconds_per_pick), 1)
        time_saved = round(max(0.0, baseline_time - estimated_time), 1)

        return {
            "order_id": order_id,
            "algorithm": algorithm,
            "complexity": complexity,
            "calculation_time_ms": calc_time_ms,
            "stop_count": k,
            "stops": ordered_tour,
            "full_path": full_path,
            "total_distance": total_distance,
            "baseline_distance": baseline_distance,
            "distance_saved_m": distance_saved,
            "percent_saved": pct_saved,
            "estimated_time_seconds": estimated_time,
            "baseline_time_seconds": baseline_time,
            "time_saved_seconds": time_saved,
            "legs": legs,
            "blocked_corridors_count": len(self.warehouse.blocked_edges) if hasattr(self.warehouse, 'blocked_edges') else 0,
            "has_hazard_detour": bool(getattr(self.warehouse, 'blocked_edges', None)),
            "unreachable": False,
            "unreachable_stops": []
        }

    # -------------------------------------------------------------
    # Exact TSP: Branch-and-Bound Permutation Enumeration (k < 8)
    # -------------------------------------------------------------
    def _solve_brute_force(self, stops, dist_cache):
        """
        Tests permutations of stops with early pruning (branch-and-bound)
        when cumulative distance exceeds the best-known upper bound.
        Guarantees exact mathematical global minimum.
        """
        best_tour = None
        best_dist = float('inf')

        for perm in itertools.permutations(stops):
            current_tour = [self.packing_shelf_id] + list(perm) + [self.packing_shelf_id]
            current_dist = 0.0
            pruned = False

            for i in range(len(current_tour) - 1):
                u = current_tour[i]
                v = current_tour[i + 1]
                current_dist += dist_cache[(u, v)]
                if current_dist >= best_dist:
                    pruned = True
                    break

            if not pruned and current_dist < best_dist:
                best_dist = current_dist
                best_tour = current_tour

        return best_tour or ([self.packing_shelf_id] + list(stops) + [self.packing_shelf_id])

    # -------------------------------------------------------------
    # Exact TSP: Held-Karp Dynamic Programming (8 <= k <= 12)
    # -------------------------------------------------------------
    def _solve_held_karp(self, stops, dist_cache):
        """
        Exact TSP via Held-Karp dynamic programming with bitmask states:
        memo[(mask, last_node_idx)] = (min_dist, prev_node_idx)
        Complexity: O(k^2 * 2^k).
        """
        k = len(stops)
        if k <= 1:
            return [self.packing_shelf_id] + list(stops) + [self.packing_shelf_id]

        node_list = [self.packing_shelf_id] + stops
        n = len(node_list)

        # dist_matrix[i][j]
        matrix = [[dist_cache[(node_list[i], node_list[j])] for j in range(n)] for i in range(n)]

        # DP table: memo[(mask, j)] = min cost to visit subset `mask` ending at node `j` (1-indexed for stops)
        # mask is bitmask of stops visited (bits 0 to k-1 corresponding to stops[0..k-1])
        memo = {}

        # Base cases: path from 0 (packing) to each stop j
        for j in range(k):
            memo[(1 << j, j)] = (matrix[0][j + 1], 0)

        # Subsets of size 2 to k
        for subset_size in range(2, k + 1):
            for subset in itertools.combinations(range(k), subset_size):
                mask = 0
                for bit in subset:
                    mask |= (1 << bit)

                for j in subset:
                    prev_mask = mask ^ (1 << j)
                    best_cost = float('inf')
                    best_prev = None

                    for m in subset:
                        if m != j and (prev_mask, m) in memo:
                            cost = memo[(prev_mask, m)][0] + matrix[m + 1][j + 1]
                            if cost < best_cost:
                                best_cost = cost
                                best_prev = m

                    if best_prev is not None:
                        memo[(mask, j)] = (best_cost, best_prev)

        # Connect back to origin (node 0)
        final_mask = (1 << k) - 1
        best_total = float('inf')
        last_stop_idx = 0

        for j in range(k):
            if (final_mask, j) in memo:
                total_cost = memo[(final_mask, j)][0] + matrix[j + 1][0]
                if total_cost < best_total:
                    best_total = total_cost
                    last_stop_idx = j

        # Reconstruct tour backwards
        tour_indices = []
        curr_mask = final_mask
        curr_j = last_stop_idx

        for _ in range(k):
            tour_indices.append(curr_j + 1)
            prev_j = memo[(curr_mask, curr_j)][1]
            curr_mask ^= (1 << curr_j)
            curr_j = prev_j

        tour_indices.reverse()
        tour = [self.packing_shelf_id] + [node_list[idx] for idx in tour_indices] + [self.packing_shelf_id]
        return tour

    # -------------------------------------------------------------
    # Greedy TSP: Nearest-Neighbor Heuristic
    # -------------------------------------------------------------
    def _solve_nearest_neighbor(self, stops, dist_cache):
        """
        Greedy Nearest-Neighbor heuristic:
        Always transitions to the unvisited shelf minimizing corridor distance.
        Time Complexity: O(k^2).
        """
        unvisited = set(stops)
        current = self.packing_shelf_id
        tour = [current]

        while unvisited:
            next_stop = min(unvisited, key=lambda s: dist_cache[(current, s)])
            tour.append(next_stop)
            unvisited.remove(next_stop)
            current = next_stop

        tour.append(self.packing_shelf_id)
        return tour

    # -------------------------------------------------------------
    # Combinatorial Metaheuristic: 2-Opt Local Search
    # -------------------------------------------------------------
    def _apply_2opt(self, tour, dist_cache, max_iterations=50):
        """
        2-Opt Local Search Heuristic:
        Systematically tests pairs of non-adjacent edges and reverses the segment
        between them to eliminate corridor loops and crossings.
        """
        best_tour = list(tour)
        improved = True
        iteration = 0

        def tour_distance(t):
            return sum(dist_cache[(t[i], t[i + 1])] for i in range(len(t) - 1))

        best_distance = tour_distance(best_tour)

        while improved and iteration < max_iterations:
            improved = False
            iteration += 1

            for i in range(1, len(best_tour) - 2):
                for j in range(i + 1, len(best_tour) - 1):
                    new_tour = best_tour[:i] + best_tour[i:j + 1][::-1] + best_tour[j + 1:]
                    new_distance = tour_distance(new_tour)

                    if new_distance < best_distance - 1e-4:
                        best_distance = new_distance
                        best_tour = new_tour
                        improved = True
                        break
                if improved:
                    break

        return best_tour

    # -------------------------------------------------------------
    # Warehouse Operational Heuristic: S-Shape (Serpentine) Routing
    # -------------------------------------------------------------
    def _solve_s_shape(self, stops, dist_cache):
        """
        Standard warehouse S-Shape (serpentine) heuristic:
        Visits aisles sequentially from left to right. Alternates traversing
        aisles top-to-bottom and bottom-to-top.
        """
        shelves = self.warehouse.shelves

        # Group stops by aisle (x coordinate)
        aisle_map = {}
        for s in stops:
            sh = shelves.get(s)
            x = sh.x if sh else 0
            y = sh.y if sh else 0
            if x not in aisle_map:
                aisle_map[x] = []
            aisle_map[x].append((y, s))

        # Sort aisles left to right
        sorted_x = sorted(aisle_map.keys())
        tour_stops = []
        reverse = False

        for x in sorted_x:
            # Sort stops within this aisle by y
            aisle_stops = sorted(aisle_map[x], key=lambda item: item[0], reverse=reverse)
            for _, s_id in aisle_stops:
                tour_stops.append(s_id)
            # Alternate direction for next visited aisle
            reverse = not reverse

        return [self.packing_shelf_id] + tour_stops + [self.packing_shelf_id]

