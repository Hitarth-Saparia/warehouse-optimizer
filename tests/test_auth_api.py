"""
tests/test_auth_api.py
Unit & Integration Tests for:
1. POST /api/auth/register
2. Strict password criteria enforcement
3. Distinguishing ACCOUNT_NOT_FOUND (404) vs INVALID_PASSWORD (401)
4. Dynamic username and role persistence
5. Token verification via GET /api/auth/me
"""

import pytest
from backend.app import app
from backend.db import get_db

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_register_strict_password_criteria(client):
    """Verifies that registration enforces 8+ chars, upper, lower, number, and special character."""
    # Test 1: Too short (< 8 chars)
    res = client.post("/api/auth/register", json={
        "name": "Alex Tester",
        "email": "short@warehouse.io",
        "password": "Pass1!",
        "role": "supervisor"
    })
    assert res.status_code == 400
    assert "8 characters" in res.get_json()["error"]

    # Test 2: Missing uppercase
    res = client.post("/api/auth/register", json={
        "name": "Alex Tester",
        "email": "noupper@warehouse.io",
        "password": "password123!",
        "role": "supervisor"
    })
    assert res.status_code == 400
    assert "uppercase" in res.get_json()["error"]

    # Test 3: Missing lowercase
    res = client.post("/api/auth/register", json={
        "name": "Alex Tester",
        "email": "nolower@warehouse.io",
        "password": "PASSWORD123!",
        "role": "supervisor"
    })
    assert res.status_code == 400
    assert "lowercase" in res.get_json()["error"]

    # Test 4: Missing number
    res = client.post("/api/auth/register", json={
        "name": "Alex Tester",
        "email": "nonumber@warehouse.io",
        "password": "Password!@#",
        "role": "supervisor"
    })
    assert res.status_code == 400
    assert "number" in res.get_json()["error"]

    # Test 5: Missing special character
    res = client.post("/api/auth/register", json={
        "name": "Alex Tester",
        "email": "nospecial@warehouse.io",
        "password": "Password123",
        "role": "supervisor"
    })
    assert res.status_code == 400
    assert "special character" in res.get_json()["error"]


def test_register_and_login_dynamic_name(client):
    """Verifies that a custom registered account preserves the exact username and role."""
    unique_email = "siddhi.test@warehouse.io"
    custom_name = "Siddhi Borawake"
    valid_password = "SecurePassword2026!"

    # Clean up test user if previously registered
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE email = %s", (unique_email,))
    conn.commit()
    conn.close()

    # 1. Register new user
    res = client.post("/api/auth/register", json={
        "name": custom_name,
        "email": unique_email,
        "password": valid_password,
        "role": "fleet"
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "success"
    assert data["user"]["name"] == custom_name
    assert data["user"]["initials"] == "SB"
    assert data["user"]["role"] == "fleet"
    assert "token" in data

    # 2. Register duplicate email should return 409 Conflict
    res_dup = client.post("/api/auth/register", json={
        "name": "Duplicate Tester",
        "email": unique_email,
        "password": valid_password,
        "role": "supervisor"
    })
    assert res_dup.status_code == 409
    assert res_dup.get_json()["code"] == "EMAIL_ALREADY_EXISTS"

    # 3. Test Login with unregistered email -> 404 ACCOUNT_NOT_FOUND
    res_not_found = client.post("/api/auth/login", json={
        "email": "unregistered.random@warehouse.io",
        "password": "AnyPassword123!"
    })
    assert res_not_found.status_code == 404
    assert res_not_found.get_json()["code"] == "ACCOUNT_NOT_FOUND"
    assert "create an account first" in res_not_found.get_json()["error"].lower()

    # 4. Test Login with registered email but incorrect password -> 401 INVALID_PASSWORD
    res_wrong_pw = client.post("/api/auth/login", json={
        "email": unique_email,
        "password": "WrongPassword999!"
    })
    assert res_wrong_pw.status_code == 401
    assert res_wrong_pw.get_json()["code"] == "INVALID_PASSWORD"
    assert "incorrect password" in res_wrong_pw.get_json()["error"].lower()

    # 5. Test Login with valid credentials -> 200 OK and exact name returned
    res_login = client.post("/api/auth/login", json={
        "email": unique_email,
        "password": valid_password
    })
    assert res_login.status_code == 200
    login_data = res_login.get_json()
    assert login_data["user"]["name"] == custom_name
    assert login_data["user"]["role"] == "fleet"
    assert login_data["user"]["initials"] == "SB"

    # 6. Verify session via /api/auth/me
    token = login_data["token"]
    res_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_me.status_code == 200
    assert res_me.get_json()["user"]["name"] == custom_name
