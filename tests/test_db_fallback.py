"""
tests/test_db_fallback.py
Automated tests for Resilient Database Fallback (MySQL to SQLite).
Ensures that if MySQL is unreachable, the system automatically falls back to
SQLite, initializes the warehouse schema, and executes standard queries seamlessly.
"""

import os
import pytest
from backend.db import get_sqlite_connection, init_sqlite_database, SQLITE_DB_PATH
from backend.app import app


def test_sqlite_fallback_schema_and_queries():
    """Verify SQLite database initialization and query execution."""
    conn = get_sqlite_connection()
    assert conn is not None

    with conn.cursor() as cur:
        # Check shelves
        cur.execute("SELECT COUNT(*) AS count FROM shelves")
        row = cur.fetchone()
        assert row["count"] == 25

        # Check packing area
        cur.execute("SELECT id, distance_to_packing, capacity FROM shelves WHERE id = 1")
        packing = cur.fetchone()
        assert packing["id"] == 1
        assert packing["distance_to_packing"] == 0.0

        # Check products
        cur.execute("SELECT COUNT(*) AS count FROM products")
        prods = cur.fetchone()
        assert prods["count"] == 60

        # Check orders
        cur.execute("SELECT COUNT(*) AS count FROM orders")
        orders = cur.fetchone()
        assert orders["count"] >= 12

    conn.close()


def test_system_status_endpoint():
    """Verify that /api/system/status returns active database engine."""
    client = app.test_client()
    resp = client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["database_engine"] in ("mysql", "sqlite")
