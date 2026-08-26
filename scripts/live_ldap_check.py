"""Live LDAP connector proof (Feature 2 Phase E2) against glauth
(compose profile `connectors`). Mirrors live_connector_check.py: create
ldap source -> PUT connector (live bind+search validate) -> manual sync
-> worker pass -> verify accounts + entitlement catalog + audit chain.

Prereq: docker compose --profile connectors up -d glauth
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
DB = os.environ.get("IAG_DB_CONTAINER", "iag-db")
GLAUTH_C = os.environ.get("IAG_GLAUTH_CONTAINER", "iag-glauth")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
SRC_NAME = "__live_ldap_connector__"
GLAUTH = "ldap://iag-glauth:3893"
BIND_DN = "cn=svc-iag,ou=svcaccts,ou=users,dc=glauth,dc=com"
BIND_PW = "iag-ldap-proof-svc"
BASE_DN = "dc=glauth,dc=com"
FILTER = "(objectClass=posixAccount)"
ACCOUNT_ATTR = "uid"


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
        ["docker", "exec", DB, "psql", "-U", "iag_migrate", "-d", "iag", "-tAc", sql],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr}")
    return r.stdout.strip()


# --- preconditions -------------------------------------------------------
try:
    r = subprocess.run(["docker", "inspect", GLAUTH_C], capture_output=True, text=True)
    assert r.returncode == 0, "glauth container not running: docker compose --profile connectors up -d glauth"
except AssertionError as e:
    sys.exit(str(e))

print("== LDAP live proof: glauth (posixAccount users, ou= groups) ==")

st, body, cookie = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
cookie = cookie.split(";")[0] if cookie else ""
assert cookie, "no session cookie"

# psql cleanup of any previous proof source (API delete has no cascade)
for tbl in ("accounts", "sync_runs", "entitlements"):
    psql(f"DELETE FROM {tbl} WHERE data_source_id IN "
         "(SELECT id FROM data_sources WHERE name LIKE '__live_ldap_connector%')")
psql("DELETE FROM data_sources WHERE name LIKE '__live_ldap_connector%'")

st, body, _ = call("POST", "/api/sources", {"name": SRC_NAME, "source_type": "ldap"}, cookie=cookie)
assert st == 200, f"create source {st}: {body}"
sid = body["id"]
print(f"source #{sid} created (type ldap)")

config = {
    "url": GLAUTH,
    "base_dn": BASE_DN,
    "bind_dn": BIND_DN,
    "filter": FILTER,
    "account_attr": ACCOUNT_ATTR,
}
st, body, _ = call("PUT", f"/api/sources/{sid}/connector",
                   {"config": config, "secret": BIND_PW}, cookie=cookie)
assert st == 200, f"connector PUT {st}: {body}"
print("connector configured + validated (bind + base search ran live against glauth)")

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
print(f"run done: {json.dumps(detail['stats'])}")

st, body, _ = call("GET", f"/api/sources/{sid}/accounts?page_size=50", cookie=cookie)
assert st == 200, f"accounts {st}: {body}"
vals = {a["account_value"]: a for a in body["items"]}
# svc-iag (bind account) is a posixAccount too and will be synced — expected
assert "lp-alice" in vals and "lp-bob" in vals, f"accounts missing: {list(vals)}"
print(f"accounts verified: {sorted(vals)}")

st, body, _ = call("GET", f"/api/entitlements?source_id={sid}&page_size=100", cookie=cookie)
assert st == 200, f"entitlements {st}: {body}"
names = {e["name"] for e in body["items"]}
# lp-alice: superheros + vpn + LiveProof-Admins (ou= groups -> RDN value)
expected = {"superheros", "vpn", "LiveProof-Admins", "svcaccts"}
missing = expected - names
assert not missing, f"entitlements missing: {missing}; got {sorted(names)}"
print(f"entitlement catalog verified: {sorted(names)}")

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"audit chain valid, {body['entries']} entries")

print("LIVE LDAP CHECK PASS")
