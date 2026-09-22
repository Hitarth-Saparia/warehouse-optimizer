"""
backend/route_optimizer.py
Traveling Salesperson Problem (TSP) for Order Picking:
- Given an order, identifies the set of shelf locations for all required items.
- Solves the shortest round-trip picking tour starting and ending at Packing Station (Shelf 1).
- Algorithm Selection:
  * If unique stops < 8: Uses Brute-Force Permutation (Exact TSP via itertools.permutations)
  * If unique stops >= 8: Uses Nearest-Neighbor Heuristic as efficient polynomial fallback.
"""

import itertools

class RouteOptimizer:
    def __init__(self, warehouse):
        """
        warehouse: an instance of the Warehouse class providing .dijkstra() and .get_distance()
        """
        self.warehouse = warehouse
        self.packing_shelf_id = 1

    def solve_order_route(self, order_id, shelf_ids):
        """
        Computes optimal picking route visiting all given shelf_ids and returning to Shelf 1.
        shelf_ids: list of int shelf IDs
        """
        # Remove duplicate stops and packing station if already present in stops
        unique_stops = list({s for s in shelf_ids if s != self.packing_shelf_id and s is not None})

        num_stops = len(unique_stops)

        if num_stops == 0:
            return {
                "order_id": order_id,
                "algorithm": "None (No Pick Stops)",
                "stop_count": 0,
                "stops": [self.packing_shelf_id],
                "full_path": [self.packing_shelf_id],
                "total_distance": 0.0,
                "legs": []
            }

        # Select Algorithm based on problem scale
        if num_stops < 8:
            algorithm = "Brute-Force Permutation (Exact TSP)"
            ordered_tour = self._solve_brute_force(unique_stops)
        else:
            algorithm = "Nearest-Neighbor Heuristic (Greedy TSP Fallback)"
            ordered_tour = self._solve_nearest_neighbor(unique_stops)

        # Build full node-by-node graph traversal and legs
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
            # Append intermediate nodes (avoiding duplicate join node)
            if len(leg_path) > 1:
                full_path.extend(leg_path[1:])

        return {
            "order_id": order_id,
            "algorithm": algorithm,
            "stop_count": num_stops,
            "stops": ordered_tour,
            "full_path": full_path,
            "total_distance": round(total_distance, 2),
            "legs": legs
        }

    def _solve_brute_force(self, stops):
        """
        Tests all N! permutations of stops and chooses the one with minimal total tour distance.
        Exact and optimal for small stop counts (N < 8).
        """
        best_tour = None
        best_distance = float('inf')

        # Cache distances between all pairs among [1] + stops
        nodes = [self.packing_shelf_id] + stops
        dist_cache = {}
        for u in nodes:
            for v in nodes:
                if (u, v) not in dist_cache:
                    d = self.warehouse.get_distance(u, v)
                    dist_cache[(u, v)] = d
                    dist_cache[(v, u)] = d

        for perm in itertools.permutations(stops):
            current_tour = [self.packing_shelf_id] + list(perm) + [self.packing_shelf_id]
            current_distance = 0.0

            for i in range(len(current_tour) - 1):
                u = current_tour[i]
                v = current_tour[i + 1]
                current_distance += dist_cache[(u, v)]
                if current_distance >= best_distance:
                    break # Prune tours that already exceed best known

            if current_distance < best_distance:
                best_distance = current_distance
                best_tour = current_tour

        return best_tour

    def _solve_nearest_neighbor(self, stops):
        """
        Greedy Nearest-Neighbor heuristic:
        Always moves to the closest unvisited shelf until all are visited, then returns to packing.
        Runs in O(N^2) time, practical for larger orders.
        """
        unvisited = set(stops)
        current = self.packing_shelf_id
        tour = [current]

        while unvisited:
            next_stop = min(unvisited, key=lambda s: self.warehouse.get_distance(current, s))
            tour.append(next_stop)
            unvisited.remove(next_stop)
            current = next_stop

        tour.append(self.packing_shelf_id)
        return tour
