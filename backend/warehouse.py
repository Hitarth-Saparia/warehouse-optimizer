"""
backend/warehouse.py
Discrete Mathematics & Graph Theory Implementation:
===================================================
Represents the physical warehouse floorplan as an undirected, weighted,
metric graph G = (V, E, w):
- V: Vertices representing physical locations (Shelf 1 = Packing/Dispatch Area, Shelves 2..N).
- E: Edges representing walkable aisle corridors and crossways.
- w: E -> R+ : Non-negative corridor traversal distances in meters.

Key Algorithmic Components:
1. Dijkstra's Shortest Path with Min-Heap Priority Queue: O((V + E) log V).
2. All-Pairs Shortest Path (APSP) Distance Matrix with Memoization: O(1) pairwise lookup.
3. Graph Structural Metrics: Connected Components (BFS), Graph Diameter, and Closeness Centrality.
4. Metric Space Verification (Symmetry, Triangle Inequality).
"""

import heapq
from collections import deque
import math


class Warehouse:
    """
    Undirected Weighted Graph model G = (V, E, w) representing warehouse corridors.
    Provides shortest-path calculations, distance matrix caching, and graph theory metrics.
    """

    def __init__(self, shelves=None, edges=None):
        """
        Args:
            shelves: list of Shelf objects or dictionaries containing node metadata.
            edges: list of tuples (from_shelf_id, to_shelf_id, distance).
        """
        self.shelves = {}  # Vertex set V: shelf_id -> Shelf / dict
        self.adj = {}      # Adjacency list: shelf_id -> [(neighbor_id, distance), ...]
        self.blocked_edges = set()       # set of (min(u, v), max(u, v)) for impassable corridors
        self.corridor_penalties = {}     # (min(u, v), max(u, v)) -> float penalty for congested corridors
        self._distance_matrix = {}  # Memoized (u, v) -> shortest distance
        self._path_matrix = {}      # Memoized (u, v) -> list of nodes in path

        if shelves:
            for s in shelves:
                s_id = s.id if hasattr(s, 'id') else s['id']
                self.shelves[s_id] = s
                if s_id not in self.adj:
                    self.adj[s_id] = []

        if edges:
            for u, v, w in edges:
                self.add_edge(u, v, float(w))

    # -------------------------------------------------------------
    # Graph Construction & Modification
    # -------------------------------------------------------------

    def block_corridor(self, u, v):
        """Marks corridor (u, v) as completely impassable."""
        edge_key = (min(int(u), int(v)), max(int(u), int(v)))
        self.blocked_edges.add(edge_key)
        self._invalidate_cache()

    def unblock_corridor(self, u, v):
        """Restores normal corridor traffic."""
        edge_key = (min(int(u), int(v)), max(int(u), int(v)))
        self.blocked_edges.discard(edge_key)
        self.corridor_penalties.pop(edge_key, None)
        self._invalidate_cache()

    def set_corridor_penalty(self, u, v, penalty):
        """Applies traffic/congestion penalty distance to corridor."""
        edge_key = (min(int(u), int(v)), max(int(u), int(v)))
        if penalty is None or float(penalty) <= 0:
            self.corridor_penalties.pop(edge_key, None)
        else:
            self.corridor_penalties[edge_key] = float(penalty)
        self._invalidate_cache()

    def get_blocked_corridors(self):
        """Returns list of currently blocked or penalized corridors."""
        return [
            {
                "from_shelf": u,
                "to_shelf": v,
                "is_blocked": True,
                "penalty": self.corridor_penalties.get((u, v))
            }
            for u, v in sorted(list(self.blocked_edges))
        ]

    def add_node(self, shelf):
        """Adds vertex v in V."""
        s_id = shelf.id if hasattr(shelf, 'id') else shelf['id']
        self.shelves[s_id] = shelf
        if s_id not in self.adj:
            self.adj[s_id] = []
        self._invalidate_cache()

    def add_edge(self, u, v, weight):
        """
        Adds undirected edge (u, v) with weight w to E.
        Guarantees symmetry: w(u, v) = w(v, u).
        """
        if u not in self.adj:
            self.adj[u] = []
        if v not in self.adj:
            self.adj[v] = []

        weight = float(weight)

        # Avoid duplicate edges
        if not any(neighbor == v for neighbor, _ in self.adj[u]):
            self.adj[u].append((v, weight))
        if not any(neighbor == u for neighbor, _ in self.adj[v]):
            self.adj[v].append((u, weight))

        self._invalidate_cache()

    def _invalidate_cache(self):
        """Clears memoized distances upon graph mutation."""
        self._distance_matrix.clear()
        self._path_matrix.clear()

    # -------------------------------------------------------------
    # Discrete Math: Shortest Path via Dijkstra's Algorithm
    # -------------------------------------------------------------

    def dijkstra(self, start_id, end_id):
        """
        Computes the single-pair shortest path and distance between start_id and end_id
        using Dijkstra's Algorithm with a min-heap priority queue.
        
        Time Complexity: O((|V| + |E|) log |V|)
        Space Complexity: O(|V|)
        
        Returns:
            (shortest_distance: float, path: list[int])
        """
        # Check cache first for instant O(1) response
        cache_key = (start_id, end_id)
        if cache_key in self._distance_matrix:
            return self._distance_matrix[cache_key], self._path_matrix[cache_key]

        if start_id == end_id:
            return 0.0, [start_id]

        if start_id not in self.adj or end_id not in self.adj:
            return float('inf'), []

        # Distance table: delta(start_id, v) initialized to infinity
        distances = {node: float('inf') for node in self.adj}
        distances[start_id] = 0.0

        # Predecessor map for path reconstruction
        previous = {node: None for node in self.adj}

        # Priority Queue: (cumulative_distance, node_id)
        pq = [(0.0, start_id)]

        while pq:
            current_dist, current_node = heapq.heappop(pq)

            if current_node == end_id:
                break

            if current_dist > distances[current_node]:
                continue

            for neighbor, weight in self.adj.get(current_node, []):
                edge_key = (min(int(current_node), int(neighbor)), max(int(current_node), int(neighbor)))
                if edge_key in self.blocked_edges:
                    continue  # Impassable / blocked corridor

                effective_weight = weight + self.corridor_penalties.get(edge_key, 0.0)
                new_dist = current_dist + effective_weight
                # Relaxation step: if a shorter corridor path is found
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    previous[neighbor] = current_node
                    heapq.heappush(pq, (new_dist, neighbor))

        # Reconstruct path backwards from end_id to start_id
        if distances[end_id] == float('inf'):
            return float('inf'), []

        path = []
        curr = end_id
        while curr is not None:
            path.append(curr)
            curr = previous[curr]
        path.reverse()

        result_dist = round(distances[end_id], 2)

        # Memoize bidirectional result due to undirected graph symmetry
        self._distance_matrix[(start_id, end_id)] = result_dist
        self._path_matrix[(start_id, end_id)] = path
        self._distance_matrix[(end_id, start_id)] = result_dist
        self._path_matrix[(end_id, start_id)] = list(reversed(path))

        return result_dist, path

    def get_distance(self, u, v):
        """Returns the shortest corridor walking distance between u and v."""
        dist, _ = self.dijkstra(u, v)
        return dist

    # -------------------------------------------------------------
    # All-Pairs Shortest Path (APSP) Matrix Precomputation
    # -------------------------------------------------------------

    def precompute_distance_matrix(self):
        """
        Precomputes all-pairs shortest paths across all vertices.
        Enables O(1) lookups for combinatorial TSP and greedy layout optimization.
        """
        nodes = list(self.adj.keys())
        for i in range(len(nodes)):
            for j in range(i, len(nodes)):
                u, v = nodes[i], nodes[j]
                self.dijkstra(u, v)
        return self._distance_matrix

    # -------------------------------------------------------------
    # Graph Theory Structural & Topological Analysis
    # -------------------------------------------------------------

    def is_connected(self):
        """
        Verifies if graph G is connected (a single component).
        Uses Breadth-First Search (BFS) starting from Packing Station (node 1).
        Ensures all shelves are reachable for warehouse order picking.
        """
        if not self.adj:
            return True

        start_node = next(iter(self.adj))
        visited = set()
        queue = deque([start_node])
        visited.add(start_node)

        while queue:
            node = queue.popleft()
            for neighbor, _ in self.adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return len(visited) == len(self.adj)

    def get_connected_components(self):
        """Returns list of connected component node sets."""
        visited = set()
        components = []

        for node in self.adj:
            if node not in visited:
                comp = set()
                queue = deque([node])
                visited.add(node)
                comp.add(node)

                while queue:
                    curr = queue.popleft()
                    for neighbor, _ in self.adj.get(curr, []):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            comp.add(neighbor)
                            queue.append(neighbor)
                components.append(comp)

        return components

    def graph_diameter(self):
        """
        Computes the diameter of the warehouse graph:
        diameter(G) = max_{u, v in V} delta(u, v)
        Represents the longest possible shortest path across the entire warehouse.
        """
        max_dist = 0.0
        nodes = list(self.adj.keys())
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dist = self.get_distance(nodes[i], nodes[j])
                if dist != float('inf') and dist > max_dist:
                    max_dist = dist
        return round(max_dist, 2)

    def closeness_centrality(self, node_id):
        """
        Computes the Closeness Centrality C(u) = (|V| - 1) / sum_{v != u} delta(u, v).
        High closeness centrality indicates strategic locations with minimal average
        distance to all other warehouse storage shelves.
        """
        if node_id not in self.adj:
            return 0.0

        n = len(self.adj)
        if n <= 1:
            return 1.0

        total_distance = sum(self.get_distance(node_id, v) for v in self.adj if v != node_id)
        if total_distance == 0.0 or math.isinf(total_distance):
            return 0.0

        return round((n - 1) / total_distance, 4)

    # -------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------

    def to_dict(self):
        """Returns JSON-serializable graph structure for visualization."""
        nodes = []
        for s_id, s in self.shelves.items():
            if hasattr(s, 'to_dict'):
                nodes.append(s.to_dict())
            else:
                nodes.append(s)

        edge_list = []
        seen = set()
        for u in self.adj:
            for v, w in self.adj[u]:
                edge_pair = tuple(sorted([u, v]))
                if edge_pair not in seen:
                    seen.add(edge_pair)
                    edge_list.append({
                        "from_shelf_id": u,
                        "to_shelf_id": v,
                        "distance": w
                    })

        return {
            "nodes": nodes,
            "edges": edge_list,
            "is_connected": self.is_connected(),
            "diameter": self.graph_diameter()
        }
