"""Phase C: SIEM pull-only feed - JSONL pages, cursor, headers, stats, guards."""
from __future__ import annotations

import json
import sqlite3

from app.models.user import Role
from tests.test_apikeys_auth import _seed_key


def _hdr(key):
    return {"Authorization": f"Bearer {key}"}


def _seed_entries(admin_client, n=6):
    for i in range(n):
        r = admin_client.post("/api/identities", json={"employee_id": f"E-FEED-{i}"})
        assert r.status_code == 200, r.text


def _pull(client, after_id=0, limit=500):
    r = client.get(f"/api/audit/feed?after_id={after_id}&limit={limit}")
    assert r.status_code == 200, r.text
    rows = [json.loads(ln) for ln in r.text.splitlines() if ln]
    return r, rows


def test_feed_full_walk_ordered_jsonl(admin_client):
    _seed_entries(admin_client)
    r, rows = _pull(admin_client)
    ids = [row["id"] for row in rows]
    assert ids == sorted(ids)
    assert len(ids) > 6
    for row in rows:
        assert set(row) >= {"id", "ts", "actor_id", "actor_username", "action",
                            "entity_type", "entity_id", "details", "prev_hash",
                            "record_hash"}
    assert isinstance(rows[0]["details"], dict)  # parsed, not double-encoded
    assert r.headers["Content-Type"].startswith("application/x-ndjson")


def test_feed_limit_and_cursor_walk(admin_client):
    _seed_entries(admin_client)
    r, page1 = _pull(admin_client, limit=3)
    assert len(page1) == 3
    assert r.headers["X-IAG-Last-Id"] == str(page1[-1]["id"])
    _, tail = _pull(admin_client, after_id=page1[-1]["id"])
    assert tail[0]["id"] > page1[-1]["id"]
    assert {row["id"] for row in page1}.isdisjoint({row["id"] for row in tail})
    _, full = _pull(admin_client)
    assert [row["id"] for row in page1 + tail] == [row["id"] for row in full]


def test_feed_empty_page_and_head_headers(admin_client):
    _seed_entries(admin_client, n=1)
    r, rows = _pull(admin_client)
    last = rows[-1]
    r2, rows2 = _pull(admin_client, after_id=last["id"])
    assert rows2 == []
    assert r2.headers["X-IAG-Last-Id"] == str(last["id"])
    assert r2.headers["X-IAG-Head"] == last["record_hash"]
    r3, rows3 = _pull(admin_client)
    assert r3.headers["X-IAG-Head"] == rows3[-1]["record_hash"]


def test_feed_matches_csv_export(admin_client):
    _seed_entries(admin_client, n=2)
    _, rows = _pull(admin_client)
    import csv as _csv
    import io as _io
    body = list(_csv.reader(_io.StringIO(admin_client.get("/api/audit/export").text)))[1:]
    assert len(body) == len(rows)
    for csv_row, feed_row in zip(body, rows):
        assert int(csv_row[0]) == feed_row["id"]
        assert csv_row[2] == feed_row["actor_username"]
        assert csv_row[3] == feed_row["action"]
        assert csv_row[7] == feed_row["record_hash"]


def test_feed_hashes_recompute_walking_pages(admin_client):
    _seed_entries(admin_client)
    prev = "0" * 64
    after = 0
    while True:
        r, rows = _pull(admin_client, after_id=after, limit=2)
        if not rows:
            break
        for row in rows:
            # Server hashes details as its canonical string; the feed ships it
            # parsed (dict), so re-canonicalize before hashing. Legacy rows
            # that fail to parse ship raw and are hashed as-is.
            if isinstance(row["details"], str):
                details_str = row["details"]
            else:
                details_str = json.dumps(row["details"], sort_keys=True,
                                         separators=(",", ":"), default=str)
            payload = {
                "action": row["action"],
                "actor_id": row["actor_id"],
                "actor_username": row["actor_username"],
                "details": details_str,
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "ts": row["ts"] + "+00:00",
            }
            material = prev + json.dumps(payload, sort_keys=True,
                                         separators=(",", ":"), default=str)
            import hashlib
            assert hashlib.sha256(material.encode()).hexdigest() == row["record_hash"]
            assert row["prev_hash"] == prev
            prev = row["record_hash"]
        after = rows[-1]["id"]
        if len(rows) < 2:
            break
    assert admin_client.get("/api/audit/verify").json()["valid"] is True


def test_stats_shape_and_tamper_detection(admin_client):
    _seed_entries(admin_client, n=1)
    s = admin_client.get("/api/audit/feed/stats").json()
    assert s["total_entries"] > 0
    assert s["last_id"] > 0
    assert s["last_ts"] is not None
    assert len(s["chain_head"]) == 64
    assert s["chain_valid"] is True
    db_path = admin_client.app.state.test_db_path
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE audit_entries SET actor_username = ? WHERE id = 2", ("mallory",))
    s2 = admin_client.get("/api/audit/feed/stats").json()
    assert s2["chain_valid"] is False


def test_feed_guards(admin_client, client):
    _seed_entries(admin_client, n=1)
    aud_key = _seed_key(client, role=Role.AUDITOR)
    rv_key = _seed_key(client, role=Role.REPORT_VIEWER)
    assert client.get("/api/audit/feed", headers=_hdr(aud_key)).status_code == 200
    assert client.get("/api/audit/feed/stats", headers=_hdr(aud_key)).status_code == 200
    assert client.get("/api/audit/feed", headers=_hdr(rv_key)).status_code == 403
    assert client.get("/api/audit/feed/stats", headers=_hdr(rv_key)).status_code == 403
    # keys are read-only principals; no write exists on the audit surface, so
    # the write choke is covered suite-wide (test_apikeys_auth).
    client.cookies.clear()
    assert client.get("/api/audit/feed").status_code == 401
