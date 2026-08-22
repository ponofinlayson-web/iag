"""Live SCIM surface smoke (phase B): bearer gate + write path on real PG.

Not the phase-E proof (no config/token endpoints yet - phase C); this
seeds the settings row directly via psql, proves the bearer gate and a
full write flow through nginx against live Postgres, then restores the
disabled state. Live-DB harness rule: unique externalIds per run.
"""
import json
import os
import secrets
import subprocess
import urllib.error
import urllib.request
import hashlib

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
TOKEN = "iag_scim_smoke_" + secrets.token_urlsafe(32)


def call(method, path, body=None, bearer=None):
    req = urllib.request.Request(BASE + path, method=method)
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/scim+json")
    try:
        with urllib.request.urlopen(req, data) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return r.status, {"_raw": raw.decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            return e.code, {}


def psql(sql):
    subprocess.run(
        ["docker", "exec", "iag-db", "psql", "-U", "iag_migrate", "-d", "iag",
         "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True, capture_output=True,
    )


def expect(cond, label, detail=""):
    assert cond, f"FAIL {label} {detail}"
    print(f"ok - {label}")


# 0. reset settings row so the script is re-runnable (a prior failed
# run may have left enabled=true with a stale token)
psql("UPDATE scim_settings SET config='{\"enabled\": false}', token_hash=NULL WHERE id=1;")

# 1. disabled surface answers 503 SCIM envelope
st, body = call("GET", "/api/scim/v2/Users")
expect(st == 503 and body.get("schemas") == ["urn:ietf:params:scim:api:messages:2.0:Error"],
       "disabled surface -> 503 SCIM envelope", f"{st} {body}")

# 2. enable + seed token directly (phase C builds the endpoint)
digest = hashlib.sha256(TOKEN.encode()).hexdigest()
suffix = os.urandom(3).hex()
psql(
    "UPDATE scim_settings SET config='{\"enabled\": true}', "
    f"token_hash='{digest}', updated_at=NOW() WHERE id=1;"
)
st, body = call("GET", "/api/scim/v2/Users", bearer=TOKEN)
expect(st == 200 and "totalResults" in body, "enabled surface + token -> list OK", f"{st} {body}")

# 3. bad bearer -> 401 envelope + WWW-Authenticate
st, body = call("GET", "/api/scim/v2/Users", bearer="totally-wrong")
expect(st == 401, "bad bearer -> 401", f"{st} {body}")

# 4. create via bearer (audit actor=scim lands same-TX)
eid = f"E-SCIM-SMOKE-{suffix}"
st, body = call("POST", "/api/scim/v2/Users", bearer=TOKEN, body={
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": f"scim-smoke-{suffix}",
    "externalId": eid,
    "name": {"givenName": "Smoke", "familyName": "Test"},
    "emails": [{"value": f"scim-smoke-{suffix}@x.io"}],
})
expect(st == 201 and body.get("id") == eid, "create 201, id=externalId", f"{st} {body}")

# 5. PATCH active=false (Okta deprovision shape)
st, body = call("PATCH", f"/api/scim/v2/Users/{eid}", bearer=TOKEN, body={
    "Operations": [{"op": "replace", "value": {"active": False}}]})
expect(st == 200 and body.get("active") is False, "PATCH active=false", f"{st} {body}")

# 6. DELETE soft
st, _ = call("DELETE", f"/api/scim/v2/Users/{eid}", bearer=TOKEN)
expect(st == 204, "DELETE 204")

# 7. filter finds the deactivated user
from urllib.parse import quote
st, body = call("GET", f"/api/scim/v2/Users?filter={quote(f'externalId eq \"{eid}\"')}", bearer=TOKEN)
expect(st == 200 and body["totalResults"] == 1
       and body["Resources"][0]["active"] is False,
       "filter by externalId after deprovision", f"{st} {body}")

# 8. audit chain carries the scim actor (login admin to read feed/stats)
pw = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
req = urllib.request.Request(BASE + "/api/auth/login", method="POST",
                             data=json.dumps({"username": "admin", "password": pw}).encode())
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req) as r:
    cookie = (r.headers.get("Set-Cookie") or "").split(";")[0]
req = urllib.request.Request(BASE + "/api/audit/feed/stats")
req.add_header("Cookie", cookie)
with urllib.request.urlopen(req) as r:
    stats = json.load(r)
expect(stats["chain_valid"] is True, "audit chain valid", str(stats))
req = urllib.request.Request(BASE + f"/api/audit/feed?limit=5000")
req.add_header("Cookie", cookie)
with urllib.request.urlopen(req) as r:
    feed = r.read().decode()
expect('"actor_username":"scim"' in feed, "scim actor visible in feed")

# 9. restore disabled state (smoke leaves no live surface)
psql("UPDATE scim_settings SET config='{\"enabled\": false}', token_hash=NULL "
     "WHERE id=1;")
st, body = call("GET", "/api/scim/v2/Users")
expect(st == 503, "surface restored to disabled", f"{st} {body}")

print("SCIM SMOKE PASS")
