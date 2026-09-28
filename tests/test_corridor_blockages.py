"""
tests/test_corridor_blockages.py
Automated tests for Dynamic Corridor Blockages & Traffic Congestion Penalties
"""

import pytest
from backend.warehouse import Warehouse
from backend.models import Shelf
from backend.app import app


def test_corridor_blockage_forces_detour():
    """
    Test graph:
      1 --- (10) --- 2 --- (10) --- 3
      |                             |
      +-------- (30) --- 4 ---------+ (30)
    Normal shortest path from 1 to 3: 1 -> 2 -> 3 (dist: 20)
    When corridor (2, 3) is blocked: path must detour via 4: 1 -> 4 -> 3 (dist: 60)
    """
    w = Warehouse()
    for i in range(1, 5):
        w.add_node(Shelf(id=i, distance_to_packing=0.0))

    w.add_edge(1, 2, 10.0)
    w.add_edge(2, 3, 10.0)
    w.add_edge(1, 4, 30.0)
    w.add_edge(4, 3, 30.0)

    # Initial state
    dist, path = w.dijkstra(1, 3)
    assert dist == 20.0
    assert path == [1, 2, 3]

    # Block corridor (2, 3)
    w.block_corridor(2, 3)
    assert len(w.get_blocked_corridors()) == 1

    dist_blocked, path_blocked = w.dijkstra(1, 3)
    assert dist_blocked == 60.0
    assert path_blocked == [1, 4, 3]

    # Unblock corridor (2, 3)
    w.unblock_corridor(2, 3)
    dist_restored, path_restored = w.dijkstra(1, 3)
    assert dist_restored == 20.0
    assert path_restored == [1, 2, 3]


def test_corridor_traffic_penalty_rerouting():
    """
    Test that traffic congestion penalty redirects picker if alternate route is shorter.
    Path A: 1 -> 2 (10)
    Path B: 1 -> 3 (7) -> 2 (7) = 14
    Direct edge (1, 2) is 10.
    If penalty of 10 is added to (1, 2), effective weight becomes 20.
    Picker should now detour via 3 (distance 14 < 20).
    """
    w = Warehouse()
    for i in range(1, 4):
        w.add_node(Shelf(id=i, distance_to_packing=0.0))

    w.add_edge(1, 2, 10.0)
    w.add_edge(1, 3, 7.0)
    w.add_edge(3, 2, 7.0)

    dist_normal, path_normal = w.dijkstra(1, 2)
    assert dist_normal == 10.0
    assert path_normal == [1, 2]

    # Add congestion penalty of 10 to edge (1, 2)
    w.set_corridor_penalty(1, 2, 10.0)
    dist_penalized, path_penalized = w.dijkstra(1, 2)
    assert dist_penalized == 14.0
    assert path_penalized == [1, 3, 2]


def test_corridor_api_endpoints():
    """Test Flask REST endpoints for blocking and clearing corridors."""
    client = app.test_client()

    # Reset any existing blocks
    resp = client.post("/api/warehouse/corridors/reset")
    assert resp.status_code == 200

    # Block corridor (2, 3)
    resp = client.post("/api/warehouse/corridor/block", json={"from_shelf": 2, "to_shelf": 3})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["total_blocked"] == 1

    # Check blocked list
    resp = client.get("/api/warehouse/corridors/blocked")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["blocked_corridors"][0]["from_shelf"] == 2
    assert data["blocked_corridors"][0]["to_shelf"] == 3

    # Unblock corridor (2, 3)
    resp = client.post("/api/warehouse/corridor/unblock", json={"from_shelf": 2, "to_shelf": 3})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["total_blocked"] == 0
