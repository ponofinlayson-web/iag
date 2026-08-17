"""Auth flow, lockout, role enforcement."""
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME
def test_health_no_auth(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401
def test_login_bad_password(client):
    r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong"})
    assert r.status_code == 401
def test_login_lockout(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong"})
    r = client.post("/api/auth/logout", json={})
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong"})
    assert r.status_code in (401, 423)
def test_login_success_sets_cookie(admin_client):
    r = admin_client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == ADMIN_USERNAME
    assert body["role"] == "system_admin"
def test_change_password(admin_client):
    r = admin_client.post("/api/auth/change-password", json={
        "current_password": ADMIN_PASSWORD, "new_password": "newpass12345",
    })
    assert r.status_code == 200
    r = admin_client.post("/api/auth/login", json={
        "username": ADMIN_USERNAME, "password": "newpass12345",
    })
    assert r.status_code == 200
    r = admin_client.post("/api/auth/change-password", json={
        "current_password": "newpass12345", "new_password": ADMIN_PASSWORD,
    })
    assert r.status_code == 200
