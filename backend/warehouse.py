"""
backend/warehouse.py
Discrete Mathematics & Graph Theory implementation:
- Represents warehouse aisles, shelves, and packing area as an undirected weighted graph.
- Implements Dijkstra's Algorithm for exact shortest path between any two locations.
"""

import heapq

class Warehouse:
    def __init__(self, shelves=None, edges=None):
        """
        shelves: list of Shelf objects or dicts
        edges: list of tuples (from_shelf_id, to_shelf_id, distance)
        """
        self.shelves = {} # shelf_id -> Shelf / dict
        self.adj = {}     # shelf_id -> [(neighbor_id, distance), ...]

        if shelves:
            for s in shelves:
                s_id = s.id if hasattr(s, 'id') else s['id']
                self.shelves[s_id] = s
                if s_id not in self.adj:
                    self.adj[s_id] = []

        if edges:
            for u, v, w in edges:
                self.add_edge(u, v, float(w))

    def add_node(self, shelf):
        s_id = shelf.id if hasattr(shelf, 'id') else shelf['id']
        self.shelves[s_id] = shelf
        if s_id not in self.adj:
            self.adj[s_id] = []

    def add_edge(self, u, v, weight):
        if u not in self.adj:
            self.adj[u] = []
        if v not in self.adj:
            self.adj[v] = []
        
        # Avoid duplicate edges
        if not any(neighbor == v for neighbor, _ in self.adj[u]):
            self.adj[u].append((v, weight))
        if not any(neighbor == u for neighbor, _ in self.adj[v]):
            self.adj[v].append((u, weight))

    def dijkstra(self, start_id, end_id):
        """
        Computes the shortest path and distance between start_id and end_id
        using Dijkstra's Algorithm with a priority queue (min-heap).
        Returns (shortest_distance, [list_of_nodes_in_path])
        """
        if start_id == end_id:
            return 0.0, [start_id]

        if start_id not in self.adj or end_id not in self.adj:
            return float('inf'), []

        # distances dict to store minimum cost to each node
        distances = {node: float('inf') for node in self.adj}
        distances[start_id] = 0.0

        # previous node tracking to reconstruct shortest path
        previous = {node: None for node in self.adj}

        # min-heap priority queue: (cost, node)
        pq = [(0.0, start_id)]

        while pq:
            current_dist, current_node = heapq.heappop(pq)

            if current_node == end_id:
                break

            if current_dist > distances[current_node]:
                continue

            for neighbor, weight in self.adj.get(current_node, []):
                new_dist = current_dist + weight
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    previous[neighbor] = current_node
                    heapq.heappush(pq, (new_dist, neighbor))

        # Reconstruct path from start to end
        if distances[end_id] == float('inf'):
            return float('inf'), []

        path = []
        curr = end_id
        while curr is not None:
            path.append(curr)
            curr = previous[curr]
        path.reverse()

        return round(distances[end_id], 2), path

    def get_distance(self, u, v):
        dist, _ = self.dijkstra(u, v)
        return dist

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
            "edges": edge_list
        }
