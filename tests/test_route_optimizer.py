"""
tests/test_route_optimizer.py
Automated tests for Combinatorial Optimization & TSP (backend/route_optimizer.py)
"""

import pytest
from backend.warehouse import Warehouse
from backend.route_optimizer import RouteOptimizer


@pytest.fixture
def sample_warehouse():
    w = Warehouse()
    # 4-node ring layout: 1 (packing) - 2 - 3 - 4 - 1
    w.add_edge(1, 2, 10.0)
    w.add_edge(2, 3, 10.0)
    w.add_edge(3, 4, 10.0)
    w.add_edge(4, 1, 10.0)
    return w


def test_tsp_exact_permutations_optimality(sample_warehouse):
    opt = RouteOptimizer(sample_warehouse)
    # Order stops: [4, 2, 3]
    res = opt.solve_order_route(1, [4, 2, 3])

    assert "Exact TSP" in res["algorithm"]
    assert res["stop_count"] == 3
    # Absolute minimum round trip around the 40m ring
    assert res["total_distance"] == 40.0
    assert res["stops"][0] == 1
    assert res["stops"][-1] == 1


def test_tsp_empty_stops(sample_warehouse):
    opt = RouteOptimizer(sample_warehouse)
    res = opt.solve_order_route(99, [])
    assert res["total_distance"] == 0.0
    assert res["stop_count"] == 0
    assert res["stops"] == [1]


def test_tsp_2opt_heuristic_large_instances():
    w = Warehouse()
    # Linear aisle with 12 stops
    for i in range(1, 12):
        w.add_edge(i, i + 1, 5.0)
    w.add_edge(12, 1, 15.0)

    opt = RouteOptimizer(w)
    # 8 stops -> triggers Nearest-Neighbor + 2-Opt
    stops = [2, 3, 4, 5, 6, 7, 8, 9]
    res = opt.solve_order_route(10, stops)

    assert "2-Opt" in res["algorithm"]
    assert res["stop_count"] == 8
    assert res["total_distance"] > 0
    assert res["stops"][0] == 1
    assert res["stops"][-1] == 1
