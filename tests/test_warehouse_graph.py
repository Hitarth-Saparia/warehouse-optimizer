"""
tests/test_warehouse_graph.py
Automated tests for Discrete Mathematics & Graph Theory (backend/warehouse.py)
"""

import pytest
from backend.warehouse import Warehouse
from backend.models import Shelf


def test_warehouse_graph_creation_and_connectivity():
    w = Warehouse()
    for i in range(1, 6):
        w.add_node(Shelf(id=i, distance_to_packing=float((i-1)*10)))

    w.add_edge(1, 2, 10.0)
    w.add_edge(2, 3, 15.0)
    w.add_edge(3, 4, 10.0)
    w.add_edge(4, 5, 12.0)

    assert w.is_connected() is True
    assert len(w.get_connected_components()) == 1


def test_dijkstra_shortest_path_optimality():
    w = Warehouse()
    # Triangle: 1-2 (10), 2-3 (15), 1-3 (30)
    w.add_edge(1, 2, 10.0)
    w.add_edge(2, 3, 15.0)
    w.add_edge(1, 3, 30.0)

    dist, path = w.dijkstra(1, 3)
    # Optimal path should go through 2 (10 + 15 = 25 < 30)
    assert dist == 25.0
    assert path == [1, 2, 3]


def test_dijkstra_memoization_cache():
    w = Warehouse()
    w.add_edge(1, 2, 8.0)
    w.add_edge(2, 3, 12.0)

    # First call: computes and memoizes
    dist1, path1 = w.dijkstra(1, 3)
    assert dist1 == 20.0

    # Symmetric key lookup in cache
    assert (1, 3) in w._distance_matrix
    assert (3, 1) in w._distance_matrix

    # Second call should pull directly from cache
    dist2, path2 = w.dijkstra(3, 1)
    assert dist2 == 20.0
    assert path2 == [3, 2, 1]


def test_triangle_inequality_metric_space():
    w = Warehouse()
    w.add_edge(1, 2, 10.0)
    w.add_edge(2, 3, 12.0)
    w.add_edge(3, 4, 8.0)

    d_12 = w.get_distance(1, 2)
    d_24 = w.get_distance(2, 4)
    d_14 = w.get_distance(1, 4)

    # Metric space triangle inequality: d(1, 4) <= d(1, 2) + d(2, 4)
    assert d_14 <= (d_12 + d_24)


def test_graph_diameter_and_centrality():
    w = Warehouse()
    # Linear graph: 1 - 2 - 3
    w.add_edge(1, 2, 10.0)
    w.add_edge(2, 3, 10.0)

    assert w.graph_diameter() == 20.0
    # Center node 2 has higher closeness centrality than endpoints 1 and 3
    c_center = w.closeness_centrality(2)
    c_endpoint = w.closeness_centrality(1)
    assert c_center > c_endpoint
