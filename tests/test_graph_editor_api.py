import pytest
from backend.app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_graph_endpoints(client):
    # 1. Fetch graph
    res = client.get("/api/warehouse/graph")
    assert res.status_code == 200
    data = res.get_json()
    assert "nodes" in data
    assert "edges" in data
    assert "products_by_shelf" in data
    assert len(data["nodes"]) >= 25

    # 2. Add a new shelf
    add_res = client.post("/api/warehouse/shelves", json={
        "id": 99,
        "x": 300,
        "y": 300,
        "capacity": 8
    })
    assert add_res.status_code == 201
    add_data = add_res.get_json()
    assert add_data["shelf"]["id"] == 99

    # 3. Add an edge to the new shelf
    edge_res = client.post("/api/warehouse/edges", json={
        "from_shelf_id": 4,
        "to_shelf_id": 99,
        "distance": 8.5
    })
    assert edge_res.status_code == 200

    # 4. Update the shelf
    put_res = client.put("/api/warehouse/shelves/99", json={
        "x": 320,
        "y": 310,
        "capacity": 10
    })
    assert put_res.status_code == 200

    # 5. Save graph layout
    save_res = client.post("/api/warehouse/graph/save", json={
        "nodes": data["nodes"],
        "edges": data["edges"]
    })
    assert save_res.status_code == 200

    # 6. Reset graph back to factory default
    reset_res = client.post("/api/warehouse/graph/reset")
    assert reset_res.status_code == 200
    reset_data = reset_res.get_json()
    assert len(reset_data["graph"]["nodes"]) == 25
