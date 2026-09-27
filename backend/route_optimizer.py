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


class RouteOptimizer:
    """
    Solves TSP picking tours across warehouse graph corridors.
    Provides exact branch-and-bound search, greedy nearest-neighbor, and 2-opt refinement.
    """

    def __init__(self, warehouse):
        """
        Args:
            warehouse: instance of Warehouse class providing shortest path corridors.
        """
        self.warehouse = warehouse
        self.packing_shelf_id = 1

    def solve_order_route(self, order_id, shelf_ids):
        """
        Computes optimal picking tour starting at Shelf 1, visiting all required
        shelf_ids, and returning to Shelf 1.

        Returns structured dictionary with tour sequence, legs, full path,
        and algorithm computational metrics.
        """
        # Filter distinct storage stops (excluding packing station)
        unique_stops = list({int(s) for s in shelf_ids if s is not None and int(s) != self.packing_shelf_id})
        k = len(unique_stops)

        if k == 0:
            return {
                "order_id": order_id,
                "algorithm": "Trivial (No Pick Stops)",
                "complexity": "O(1)",
                "stop_count": 0,
                "stops": [self.packing_shelf_id],
                "full_path": [self.packing_shelf_id],
                "total_distance": 0.0,
                "legs": []
            }

        # Build pairwise distance cache between all candidate tour nodes
        tour_nodes = [self.packing_shelf_id] + unique_stops
        dist_cache = {}
        for u in tour_nodes:
            for v in tour_nodes:
                if (u, v) not in dist_cache:
                    d = self.warehouse.get_distance(u, v)
                    dist_cache[(u, v)] = d
                    dist_cache[(v, u)] = d

        # Algorithm Selection based on combinatorial complexity
        if k < 8:
            algorithm = "Brute-Force Permutation (Exact TSP)"
            complexity = f"O({k}! - Exact Optimum)"
            ordered_tour = self._solve_brute_force(unique_stops, dist_cache)
        else:
            algorithm = "Nearest-Neighbor + 2-Opt Local Search (Greedy TSP Fallback)"
            complexity = f"O({k}^2 - Approximation with 2-Opt)"
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
                "distance": leg_dist,
                "path": leg_path
            })
            # Append intermediate corridor nodes (avoiding duplicate join vertex)
            if len(leg_path) > 1:
                full_path.extend(leg_path[1:])

        return {
            "order_id": order_id,
            "algorithm": algorithm,
            "complexity": complexity,
            "stop_count": k,
            "stops": ordered_tour,
            "full_path": full_path,
            "total_distance": round(total_distance, 2),
            "legs": legs
        }

    # -------------------------------------------------------------
    # Exact TSP: Branch-and-Bound Permutation Enumeration
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

        return best_tour

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
        Systematically tests pairs of non-adjacent edges (u1, v1) and (u2, v2)
        and reverses the segment between them if:
            dist(u1, u2) + dist(v1, v2) < dist(u1, v1) + dist(u2, v2)
        
        Eliminates sub-optimal corridor loops and self-intersections.
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

            # Check all edge pairs (excluding fixed origin packing station at 0 and end)
            for i in range(1, len(best_tour) - 2):
                for j in range(i + 1, len(best_tour) - 1):
                    # Candidate 2-opt move: reverse sub-tour between i and j
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
