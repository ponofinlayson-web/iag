"""Risk API: run trigger, snapshot reads, guards, API-key access."""
from __future__ import annotations

import asyncio
import io
import json

from app.core.security import hash_password
from app.db import get_db
from app.models.identity import Identity
from app.models.user import Role, User

PEOPLE_CSV = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    "E-1,dora,dora@x.io,Dora,Danger,Security,\n"
    "E-2,sam,sam@x.io,Sam,Safe,Finance,E-1\n"
    "E-3,gus,gus@x.io,Gus,Ghost,IT,\n"
)
PAY_CSV = (
    "account,entitlement,privilege\n"
    "dora,Payments Admin,high\n"
    "sam,Payments Approver,moderate\n"
)
ERP_CSV = (
    "account,entitlement,privilege\n"
    "dora,ERP Deploy,very_high\n"
    "sam,ERP Read,low\n"
)


def _seed(admin_client):
    r = admin_client.post(
        "/api/identities/import",
        files={"file": ("people.csv", io.BytesIO(PEOPLE_CSV.encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text
    ids = {
        i["employee_id"]: i["id"] for i in admin_client.get("/api/identities").json()["items"]
    }
    for name, csv_text in (("Payroll", PAY_CSV), ("ERP", ERP_CSV)):
        r = admin_client.post(
            "/api/sources",
            json={"name": name, "source_type": "csv", "owner_employee_id": "E-ADMIN"},
        )
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        r = admin_client.post(
            f"/api/sources/{sid}/upload",
            files={"file": ("a.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        admin_client.post(f"/api/sources/{sid}/accounts/bulk-link", json={"match_on": "username"})
    return ids


def _direct_session(client):
    """Session on the override engine (creates tables + admin on first call)."""
    override = client.app.dependency_overrides[get_db]

    async def _go():
        gen = override()
        s = await gen.__anext__()
        try:
            yield s
        finally:
            await gen.aclose()

    return _go()


def _seed_user(client, username, role, password="pass-word-123"):
    """Cookie-login user with an arbitrary role; login cookie set on client."""

    async def _make():
        async for s in _direct_session(client):
            ident = Identity(employee_id=f"E-{username.upper()}", username=username,
                             email=f"{username}@x.io")
            s.add(ident)
            await s.flush()
            s.add(User(identity_id=ident.id, password_hash=hash_password(password), role=role))
            await s.commit()

    asyncio.run(_make())
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _set_active(client, employee_id: str, active: bool):
    async def _flip():
        async for s in _direct_session(client):
            await s.execute(
                Identity.__table__.update()
                .where(Identity.employee_id == employee_id)
                .values(is_active=active)
            )
            await s.commit()

    asyncio.run(_flip())


def _seed_key(client, role):
    from tests.test_apikeys_auth import _seed_key as _sk

    return _sk(client, role=role)


def _hdr(key):
    return {"Authorization": f"Bearer {key}"}


def test_runs_scores_and_persists(admin_client):
    _seed(admin_client)
    r = admin_client.post("/api/risk/runs")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["scored_identities"] == 4  # E-ADMIN, E-1, E-2, E-3
    assert len(body["run_id"]) == 32  # uuid4 hex
    assert sum(body["band_distribution"].values()) == 4
    r = admin_client.get("/api/risk/snapshots")
    data = r.json()
    assert data["total"] == 4
    dora = next(i for i in data["items"] if i["employee_id"] == "E-1")
    # dora: high(1) + very_high(2) = 3 weighted of 10 -> 6.0 of 20
    assert dora["signals"]["privileged_access"] == 6.0
    assert dora["score"] > 0 and dora["band"] in ("medium", "high", "critical")
    assert dora["department"] == "Security"
    assert dora["name"] == "Dora Danger"
    assert admin_client.get("/api/audit/verify").json()["valid"] is True


def test_inactive_identities_excluded(admin_client, client):
    _seed(admin_client)
    _set_active(client, "E-3", False)
    r = admin_client.post("/api/risk/runs")
    assert r.json()["scored_identities"] == 3
    r = admin_client.get("/api/risk/snapshots")
    assert all(i["employee_id"] != "E-3" for i in r.json()["items"])


def test_snapshots_run_id_and_filters(admin_client):
    _seed(admin_client)
    first = admin_client.post("/api/risk/runs").json()
    second = admin_client.post("/api/risk/runs").json()
    assert first["run_id"] != second["run_id"]
    r = admin_client.get("/api/risk/snapshots")
    assert r.json()["run_id"] == second["run_id"]
    r = admin_client.get(f"/api/risk/snapshots?run_id={first['run_id']}")
    assert r.json()["run_id"] == first["run_id"]
    assert r.json()["total"] == 4
    r = admin_client.get("/api/risk/snapshots?band=low")
    assert {i["band"] for i in r.json()["items"]} <= {"low"}
    r = admin_client.get("/api/risk/snapshots?department=Security")
    assert {i["employee_id"] for i in r.json()["items"]} == {"E-1"}


def test_trend_across_runs(admin_client):
    ids = _seed(admin_client)
    first = admin_client.post("/api/risk/runs").json()
    second = admin_client.post("/api/risk/runs").json()
    r = admin_client.get(f"/api/risk/trend/{ids['E-1']}")
    assert r.status_code == 200
    tr = r.json()["items"]
    assert [t["run_id"] for t in tr] == [first["run_id"], second["run_id"]]
    assert tr[0]["score"] == tr[1]["score"]  # nothing changed between runs
    assert admin_client.get("/api/risk/trend/99999").status_code == 404


def test_summary_shape(admin_client):
    _seed(admin_client)
    run = admin_client.post("/api/risk/runs").json()
    s = admin_client.get("/api/risk/summary").json()
    assert s["run_id"] == run["run_id"]
    assert s["run_at"] is not None
    assert s["scored_identities"] == 4
    assert sum(s["band_distribution"].values()) == 4
    assert len(s["top_risky"]) == 4
    scores = [t["score"] for t in s["top_risky"]]
    assert scores == sorted(scores, reverse=True)
    assert s["top_risky"][0]["top_factors"]  # dora has nonzero factors
    assert len(s["top_risky"][0]["top_factors"]) <= 3


def test_admin_only_portfolio_runs_clean(admin_client):
    # The seeded admin identity is the floor: one active identity, no
    # accounts -> score 0, band low, clean shapes everywhere.
    r = admin_client.post("/api/risk/runs")
    assert r.status_code == 202
    body = r.json()
    assert body["scored_identities"] == 1
    assert body["average_score"] == 0.0
    assert body["band_distribution"] == {"low": 1}
    s = admin_client.get("/api/risk/summary").json()
    assert s["run_id"] is not None and s["scored_identities"] == 1
    assert s["top_risky"][0]["employee_id"] == "E-ADMIN"
    assert admin_client.get("/api/risk/snapshots").json()["total"] == 1


def test_guards_reviewer_and_keys(admin_client, client):
    _seed(admin_client)
    aud_key = _seed_key(client, Role.AUDITOR)
    rv_key = _seed_key(client, Role.REPORT_VIEWER)
    admin_client.post("/api/risk/runs")  # populate reads
    # API keys are read-only principals: POST /runs 403 even for auditor
    assert admin_client.post("/api/risk/runs", headers=_hdr(aud_key)).status_code == 403
    for key in (aud_key, rv_key):
        for path in ("/api/risk/snapshots", "/api/risk/summary", "/api/risk/trend/1"):
            assert client.get(path, headers=_hdr(key)).status_code == 200
    # unauthenticated: 401 (client and admin_client share one cookie jar)
    client.cookies.clear()
    assert client.get("/api/risk/summary").status_code == 401
    # reviewer session user: valid login, wrong role -> 403 on all four
    _seed_user(client, "rev3", Role.REVIEWER)
    assert client.post("/api/risk/runs").status_code == 403
    for path in ("snapshots", "summary", "trend/1"):
        assert client.get(f"/api/risk/{path}").status_code == 403


def test_run_audit_details(admin_client):
    _seed(admin_client)
    run_id = admin_client.post("/api/risk/runs").json()["run_id"]
    entries = admin_client.get("/api/audit?action=risk_run_completed").json()["items"]
    assert entries
    details = json.loads(entries[0]["details"])
    assert details["run_id"] == run_id and details["scored"] == 4
    assert "band_distribution" in details
