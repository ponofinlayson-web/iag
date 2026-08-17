"""Tamper-evidence: mutate a row with raw SQL, chain verification must fail."""
import sqlite3
def test_chain_detects_tampering(admin_client):
    r = admin_client.get("/api/audit/verify")
    assert r.status_code == 200
    assert r.json()["valid"] is True
    db_path = admin_client.app.state.test_db_path
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE audit_entries SET actor_username = ? WHERE id = 1", ("mallory",))
    r = admin_client.get("/api/audit/verify")
    body = r.json()
    assert body["valid"] is False
    assert body["broken_at"] == 1
