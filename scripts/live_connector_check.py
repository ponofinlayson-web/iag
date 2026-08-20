"""Live connector proof (Feature 2 Phase E): SQL connector configured
against the stack's own Postgres — plant a demo table, configure the
connector via the API (validate runs a real LIMIT 1 query), trigger a
manual sync, wait for the worker pass, verify accounts/entitlements
landed and the audit chain stayed valid. Self-referencing: no external
DB needed. Delete the planted rows afterwards.

Usage: python scripts/live_connector_check.py   (needs IAG_BOOTSTRAP_ADMIN_PASSWORD
and IAG_APP_DB_PASSWORD in env / .env like the other live checks)
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import subprocess

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
APP_DB_PW = os.environ.get("IAG_APP_DB_PASSWORD", "")

TAG = "liveproof"
SRC_NAME = f"__live_sql_connector__"


def call(method, path, body=None, cookie=None):
    req = urllib.request.Request(BASE + path, method=method)
    if cookie:
        req.add_header("Cookie", cookie)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data) as r:
            sc = r.headers.get("Set-Cookie", "")
            return r.status, json.loads(r.read()), sc
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw.decode("utf-8", "replace")[:200]}
        return e.code, parsed, ""


def psql(sql):
    r = subprocess.run(
        ["docker", "exec", "iag-db", "psql", "-U", "iag_migrate", "-d", "iag", "-tAc", sql],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr}")
    return r.stdout.strip()


print("== planting demo access table (schema public, dropped at end) ==")
psql("DROP TABLE IF EXISTS live_connector_demo")
psql(
    "CREATE TABLE live_connector_demo (account TEXT, entitlement TEXT, privilege TEXT); "
    "INSERT INTO live_connector_demo VALUES "
    "('lp-alice','LiveProof-Admins','high'),"
    "('lp-bob','LiveProof-Viewers','low')"
)
n = psql("SELECT count(*) FROM live_connector_demo")
assert n == "2", f"plant failed: {n!r}"
print(f"planted live_connector_demo rows=2 [{n}]")

st, body, cookie = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
cookie = cookie.split(";")[0] if cookie else ""
assert cookie, "no session cookie"

# fresh source for the run (psql cleanup: API delete has no cascade)
for tbl in ("accounts", "sync_runs", "entitlements"):
    psql(f"DELETE FROM {tbl} WHERE data_source_id IN "
         "(SELECT id FROM data_sources WHERE name LIKE '__live_sql_connector%')")
psql("DELETE FROM data_sources WHERE name LIKE '__live_sql_connector%'")

st, body, _ = call("POST", "/api/sources", {"name": SRC_NAME, "source_type": "sql"}, cookie=cookie)
assert st == 200, f"create source {st}: {body}"
sid = body["id"]
print(f"source #{sid} created (type sql)")

config = {
    "url": f"postgresql+psycopg2://iag_app:$SECRET@iag-db:5432/iag",
    "query": "SELECT account, entitlement, privilege FROM live_connector_demo",
}
st, body, _ = call("PUT", f"/api/sources/{sid}/connector",
                   {"config": config, "secret": APP_DB_PW}, cookie=cookie)
if st != 200:
    psql("DROP TABLE IF EXISTS live_connector_demo")
    raise SystemExit(f"connector PUT {st}: {body}")
print(f"connector configured + validated (LIMIT 1 ran live against Postgres)")

st, body, _ = call("POST", f"/api/sources/{sid}/sync", cookie=cookie)
assert st == 200, f"sync trigger {st}: {body}"
rid = body["run_id"]
print(f"manual sync run #{rid} enqueued")

deadline = time.time() + 90
status = None
detail = {}
while time.time() < deadline:
    st, detail, _ = call("GET", f"/api/syncs/{rid}", cookie=cookie)
    assert st == 200, f"sync detail {st}: {detail}"
    status = detail["status"]
    if status in ("done", "failed", "cancelled"):
        break
    time.sleep(2)
assert status == "done", f"run did not finish: {detail}"
stats = detail["stats"]
print(f"run done: {json.dumps(stats)}")

st, body, _ = call("GET", f"/api/sources/{sid}/accounts?page_size=50", cookie=cookie)
assert st == 200, f"accounts {st}: {body}"
vals = {a["account_value"]: a for a in body["items"]}
assert "lp-alice" in vals and "lp-bob" in vals, f"accounts missing: {list(vals)}"
assert vals["lp-alice"]["privilege_level"] == "high", vals["lp-alice"]
print("accounts verified: lp-alice(high), lp-bob(low)")

# entitlement catalog is the membership truth for connector sources
# (Account.entitlement_id intentionally untouched — settled Phase B)
st, body, _ = call("GET", f"/api/entitlements?source_id={sid}&page_size=50", cookie=cookie)
assert st == 200, f"entitlements {st}: {body}"
names = {e["name"] for e in body["items"]}
assert {"LiveProof-Admins", "LiveProof-Viewers"} <= names, names
print(f"entitlement catalog verified: {sorted(names)}")

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"audit chain valid, {body['entries']} entries")

# 409 while in-flight is worker-owned timing; verify the guard cheaply:
# a completed run must NOT be cancellable
st, body, _ = call("POST", f"/api/syncs/{rid}/cancel", cookie=cookie)
assert st == 409, f"cancel of finished run should 409, got {st}: {body}"
print("cancel-on-finished correctly 409")

psql("DROP TABLE IF EXISTS live_connector_demo")
print("demo table dropped")
print("LIVE CONNECTOR CHECK PASS")
