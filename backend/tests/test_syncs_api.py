"""Phase D API tests: PUT connector (validate-at-save), POST sync
(409 in-flight / 400 no-adapter), run history, run detail, cancel,
connector block in source responses. SQLite; sql adapter happy paths
run against a real on-disk SQLite file (real engine, no network)."""
import io
import json
import sqlite3

from fastapi.testclient import TestClient

CSV = ("employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
       "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n")


def _make_source(client: TestClient, stype="sql") -> int:
    client.post("/api/identities/import",
                files={"file": ("p.csv", io.BytesIO(CSV.encode()), "text/csv")})
    r = client.post("/api/sources", json={"name": "SRC", "source_type": stype})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upstream_db(tmp_path) -> str:
    db = tmp_path / "upstream.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE access (account TEXT, entitlement TEXT, privilege TEXT);"
        "INSERT INTO access VALUES ('alice', 'Eng-Admins', 'high');"
    )
    con.commit()
    con.close()
    return str(db)


def _sql_config(db_path: str) -> dict:
    return {
        "url": f"sqlite:///{db_path}",
        "query": "SELECT account, entitlement, privilege FROM access",
    }


def test_put_connector_validates_and_saves(admin_client, tmp_path):
    sid = _make_source(admin_client)
    r = admin_client.put(f"/api/sources/{sid}/connector", json={
        "config": _sql_config(_upstream_db(tmp_path)),
        "secret": "pw",
        "sync_interval_minutes": 30,
    })
    assert r.status_code == 200, r.text
    assert r.json()["validated"] is True
    src = admin_client.get(f"/api/sources/{sid}").json()
    c = src["connector"]
    assert c["configured"] is True and c["has_secret"] is True
    assert c["interval_minutes"] == 30 and c["next_sync_at"] is not None


def test_put_connector_rejects_bad_query(admin_client, tmp_path):
    sid = _make_source(admin_client)
    bad = _sql_config(_upstream_db(tmp_path))
    bad["query"] = "DELETE FROM access"
    r = admin_client.put(f"/api/sources/{sid}/connector",
                         json={"config": bad})
    assert r.status_code == 400
    assert "SELECT" in r.json()["detail"]
    # nothing saved
    src = admin_client.get(f"/api/sources/{sid}").json()
    assert src["connector"]["configured"] is False


def test_put_connector_rejects_csv_source(admin_client):
    sid = _make_source(admin_client, stype="csv")
    r = admin_client.put(f"/api/sources/{sid}/connector",
                         json={"config": {"x": 1}})
    assert r.status_code == 400


def test_put_connector_ldap_fail_fast_no_network(admin_client):
    """Missing base_dn dies at validate — proves the sync validate call
    happens at save time without any wire."""
    sid = _make_source(admin_client, stype="ldap")
    r = admin_client.put(f"/api/sources/{sid}/connector",
                         json={"config": {"url": "ldap://nowhere:389"}})
    assert r.status_code == 400
    assert "base_dn" in r.json()["detail"]


def test_put_connector_empty_secret_keeps_existing(admin_client, tmp_path):
    sid = _make_source(admin_client)
    db = _upstream_db(tmp_path)
    r = admin_client.put(f"/api/sources/{sid}/connector", json={
        "config": _sql_config(db), "secret": "original",
    })
    assert r.status_code == 200, r.text
    r = admin_client.put(f"/api/sources/{sid}/connector", json={
        "config": _sql_config(db), "secret": "",
        "sync_interval_minutes": 60,
    })
    assert r.status_code == 200, r.text
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        secret = con.execute(
            "SELECT connector_secret FROM data_sources WHERE id=?", (sid,)
        ).fetchone()[0]
    finally:
        con.close()
    assert secret == "original"


def test_post_sync_then_409_while_inflight(admin_client, tmp_path):
    sid = _make_source(admin_client)
    r = admin_client.put(f"/api/sources/{sid}/connector", json={
        "config": _sql_config(_upstream_db(tmp_path)),
    })
    assert r.status_code == 200, r.text
    r = admin_client.post(f"/api/sources/{sid}/sync")
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    r2 = admin_client.post(f"/api/sources/{sid}/sync")
    assert r2.status_code == 409
    # run visible in history + detail (pending; no worker in tests)
    hist = admin_client.get(f"/api/sources/{sid}/syncs").json()
    assert hist["total"] == 1 and hist["items"][0]["id"] == rid
    assert hist["items"][0]["status"] == "pending"
    det = admin_client.get(f"/api/syncs/{rid}").json()
    assert det["id"] == rid and det["triggered_by"] == "manual"


def test_post_sync_requires_config(admin_client):
    sid = _make_source(admin_client)
    r = admin_client.post(f"/api/sources/{sid}/sync")
    assert r.status_code == 400
    assert "config" in r.json()["detail"]


def test_post_sync_rejects_csv(admin_client):
    sid = _make_source(admin_client, stype="csv")
    r = admin_client.post(f"/api/sources/{sid}/sync")
    assert r.status_code == 400


def test_cancel_pending_run(admin_client, tmp_path):
    sid = _make_source(admin_client)
    admin_client.put(f"/api/sources/{sid}/connector", json={
        "config": _sql_config(_upstream_db(tmp_path)),
    })
    rid = admin_client.post(f"/api/sources/{sid}/sync").json()["run_id"]
    r = admin_client.post(f"/api/syncs/{rid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # second cancel -> 409 (already finished)
    r2 = admin_client.post(f"/api/syncs/{rid}/cancel")
    assert r2.status_code == 409
    hist = admin_client.get(f"/api/sources/{sid}/syncs").json()
    assert hist["items"][0]["status"] == "cancelled"


def test_list_sources_has_connector_block(admin_client):
    sid = _make_source(admin_client, stype="csv")
    items = admin_client.get("/api/sources").json()["items"]
    mine = [s for s in items if s["id"] == sid][0]
    c = mine["connector"]
    assert set(c) == {"configured", "interval_minutes", "next_sync_at",
                      "has_secret", "last_run_status"}
    assert c["configured"] is False and c["last_run_status"] is None


def test_manual_sync_end_to_end_via_api(admin_client, worker_session, tmp_path):
    """PUT connector (validated) -> POST sync -> worker run_pass (real
    registry) -> run history shows done with stats."""
    import asyncio
    from datetime import timedelta

    from app.models.identity import utcnow
    from app.models.source import DataSource
    from app.core.sync_worker import run_pass

    sid = _make_source(admin_client)
    r = admin_client.put(f"/api/sources/{sid}/connector", json={
        "config": _sql_config(_upstream_db(tmp_path)),
    })
    assert r.status_code == 200, r.text
    rid = admin_client.post(f"/api/sources/{sid}/sync").json()["run_id"]

    # make the source due too so the same pass can claim the manual run
    async def go():
        async with worker_session() as maker:
            async with maker() as s:
                src = await s.get(DataSource, sid)
                src.next_sync_at = utcnow() - timedelta(minutes=5)
                await s.commit()
            return await run_pass(maker)

    stats = asyncio.run(go())
    assert stats["claimed"] == 1 and stats["completed"] == 1, stats
    det = admin_client.get(f"/api/syncs/{rid}").json()
    assert det["status"] == "done"
    assert det["stats"]["accounts_created"] == 1
    assert det["stats"]["entitlements_created"] == 1
    assert admin_client.get("/api/audit/verify").json()["valid"] is True
