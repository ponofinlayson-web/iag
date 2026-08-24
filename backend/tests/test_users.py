"""Feature 7 D1: users router — CRUD surface, guards, audit, auth effects."""
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME

NEW_PW = "newpass12345"


def _identity(admin_client, employee_id="E-U1", username="u1"):
    r = admin_client.post("/api/identities", json={
        "employee_id": employee_id, "username": username,
        "email": f"{username}@test.local", "first_name": "User",
        "last_name": "One", "department": "Ops",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_user(admin_client, identity_id, role="reviewer", password="passw0rd1"):
    r = admin_client.post("/api/users", json={
        "identity_id": identity_id, "role": role, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _login_as(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def _login_admin(client):
    _login_as(client, ADMIN_USERNAME, ADMIN_PASSWORD)


def test_create_and_list(admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    assert u["username"] == "u1"
    assert u["role"] == "reviewer"
    assert u["must_change_password"] is True
    assert u["is_active"] is True
    items = admin_client.get("/api/users").json()["items"]
    assert [i["username"] for i in items] == [ADMIN_USERNAME, "u1"]
    # list carries last_login from the admin own login audit row
    assert items[0]["last_login"] is not None
    assert items[1]["last_login"] is None


def test_create_missing_identity_404(admin_client):
    r = admin_client.post("/api/users", json={
        "identity_id": 99999, "role": "reviewer", "password": "passw0rd1",
    })
    assert r.status_code == 404


def test_create_second_user_same_identity_409(admin_client):
    ident = _identity(admin_client)
    _make_user(admin_client, ident)
    r = admin_client.post("/api/users", json={
        "identity_id": ident, "role": "auditor", "password": "passw0rd1",
    })
    assert r.status_code == 409


def test_short_password_422(admin_client):
    ident = _identity(admin_client)
    r = admin_client.post("/api/users", json={
        "identity_id": ident, "role": "reviewer", "password": "short",
    })
    assert r.status_code == 422


def test_detail(admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    d = admin_client.get(f"/api/users/{u['id']}").json()
    assert d["username"] == "u1"
    assert d["recent_activity_count"] >= 0


def test_role_change_and_self_guard(admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    r = admin_client.put(f"/api/users/{u['id']}/role", json={"role": "auditor"})
    assert r.status_code == 200
    assert r.json()["role"] == "auditor"
    me = admin_client.get("/api/auth/me").json()
    r = admin_client.put(f"/api/users/{me['id']}/role", json={"role": "auditor"})
    assert r.status_code == 400
    assert "own role" in r.json()["detail"]


def test_deactivate_and_self_guard(client, admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    r = admin_client.put(f"/api/users/{u['id']}/status", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    # login blocked once deactivated
    r = client.post("/api/auth/login", json={"username": "u1", "password": "passw0rd1"})
    assert r.status_code == 403
    # reactivate restores login
    admin_client.put(f"/api/users/{u['id']}/status", json={"is_active": True})
    assert client.post("/api/auth/login", json={
        "username": "u1", "password": "passw0rd1"}).status_code == 200
    # self-deactivate is refused (client now holds the u1 cookie: restore admin)
    _login_admin(client)
    me = admin_client.get("/api/auth/me").json()
    assert me["username"] == ADMIN_USERNAME
    r = admin_client.put(f"/api/users/{me['id']}/status", json={"is_active": False})
    assert r.status_code == 400
    assert "own account" in r.json()["detail"]


def test_unlock(client, admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "u1", "password": "nope"})
    r = client.post("/api/auth/login", json={"username": "u1", "password": "passw0rd1"})
    assert r.status_code == 423
    row = [i for i in admin_client.get("/api/users").json()["items"]
           if i["id"] == u["id"]][0]
    assert row["failed_attempts"] >= 5
    assert row["locked_until"] is not None
    r = admin_client.put(f"/api/users/{u['id']}/unlock")
    assert r.status_code == 200
    assert r.json()["failed_attempts"] == 0
    assert r.json()["locked_until"] is None
    assert client.post("/api/auth/login", json={
        "username": "u1", "password": "passw0rd1"}).status_code == 200


def test_reset_password_flow(client, admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    _login_as(client, "u1", "passw0rd1")
    client.post("/api/auth/change-password", json={
        "current_password": "passw0rd1", "new_password": NEW_PW})
    _login_admin(client)
    r = admin_client.put(f"/api/users/{u['id']}/reset-password", json={"password": "adminset1"})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    r = client.post("/api/auth/login", json={"username": "u1", "password": NEW_PW})
    assert r.status_code == 401  # old password dead
    r = client.post("/api/auth/login", json={"username": "u1", "password": "adminset1"})
    assert r.status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["must_change_password"] is True


def test_must_change_password_reflected_in_me(client, admin_client):
    ident = _identity(admin_client)
    _make_user(admin_client, ident)
    _login_as(client, "u1", "passw0rd1")
    me = client.get("/api/auth/me").json()
    assert me["must_change_password"] is True


def test_login_as_created_user(client, admin_client):
    ident = _identity(admin_client)
    _make_user(admin_client, ident, role="auditor")
    r = client.post("/api/auth/login", json={"username": "u1", "password": "passw0rd1"})
    assert r.status_code == 200
    assert r.json()["role"] == "auditor"


def test_cert_admin_403(client, admin_client):
    ident = _identity(admin_client)
    _make_user(admin_client, ident, role="certification_admin")
    _login_as(client, "u1", "passw0rd1")
    assert client.get("/api/users").status_code == 403
    ident2 = _identity(admin_client, "E-U2", "u2")
    assert client.post("/api/users", json={
        "identity_id": ident2, "role": "reviewer", "password": "passw0rd1",
    }).status_code == 403


def test_audit_rows_written(admin_client):
    ident = _identity(admin_client)
    u = _make_user(admin_client, ident)
    admin_client.put(f"/api/users/{u['id']}/role", json={"role": "auditor"})
    admin_client.put(f"/api/users/{u['id']}/unlock")
    for action in ("user_created", "user_role_changed", "user_unlocked"):
        r = admin_client.get("/api/audit", params={"action": action})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert any(i["entity_id"] == u["id"] for i in items), action
    # the hash chain still verifies with the new entries
    assert admin_client.get("/api/audit/verify").json()["valid"] is True


def test_404s(admin_client):
    assert admin_client.get("/api/users/99999").status_code == 404
    assert admin_client.put("/api/users/99999/role", json={"role": "auditor"}).status_code == 404
