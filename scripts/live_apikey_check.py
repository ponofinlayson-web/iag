"""Live API-key lifecycle check against the running stack (real Postgres path).

Proves feature 4 end to end: admin creates a key via cookie session, the
key reads via Bearer, chokes fire (read-only, keys-manage-keys), revoke
kills it, audit chain still verifies. Row is left revoked on purpose -
it is audit evidence (house DB-residue convention).
"""
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")


def call(method, path, body=None, cookie=None, bearer=None):
    req = urllib.request.Request(BASE + path, method=method)
    if cookie:
        req.add_header("Cookie", cookie)
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data) as r:
            sc = r.headers.get("Set-Cookie", "")
            raw = r.read()
            try:
                return r.status, json.loads(raw or b"{}"), sc
            except json.JSONDecodeError:
                return r.status, {"_raw": raw.decode("utf-8", "replace")}, sc
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), ""
        except json.JSONDecodeError:
            return e.code, {}, ""


def expect(cond, label, detail=""):
    assert cond, f"FAIL {label} {detail}"
    print(f"ok - {label}")


st, body, cookie = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
cookie = cookie.split(";")[0] if cookie else ""
assert cookie, "no session cookie"
print("ok - admin login (cookie)")

name = f"live-probe-{os.urandom(3).hex()}"
st, body, _ = call("POST", "/api/api-keys",
                   {"name": name, "role": "auditor",
                    "expires_at": "2030-01-01T00:00:00Z"}, cookie=cookie)
assert st == 201, f"create {st}: {body}"
key = body["key"]
kid = body["id"]
expect(key.startswith("iag_"), "create returns full key", key[:12] + "...")
expect(body["key_prefix"] == key[:8], "prefix matches key head")

st, body, _ = call("GET", "/api/api-keys", bearer=key)
expect(st == 403 and "manage" in body.get("detail", ""), "key cannot list keys", st)

st, body, _ = call("GET", "/api/dashboard", bearer=key)
expect(st == 200 and body.get("principal") == "api_key", "key reads dashboard (mixed payload)", st)

st, body, _ = call("GET", "/api/audit/export", bearer=key)
expect(st == 200 and len(body.get("_raw", "")) > 20, "key (auditor) exports audit CSV", st)

st, body, _ = call("GET", "/api/identities", bearer=key)
expect(st == 200, "key reads identities", st)

st, body, _ = call("POST", "/api/identities", {}, bearer=key)
expect(st == 403 and "read-only" in body.get("detail", ""), "write choked", st)

st, body, _ = call("POST", "/api/api-keys", {"name": "x", "role": "auditor"}, bearer=key)
# POST trips the read-only choke first (method check precedes the path
# check in deps.py); either 403 message proves a key cannot mint keys.
expect(st == 403 and ("manage" in body.get("detail", "") or "read-only" in body.get("detail", "")),
       "key cannot mint keys", f"{st} {body.get('detail', '')}")

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken pre-revoke: {body}"
print(f"ok - audit chain valid ({body['entries']} entries)")

st, body, _ = call("POST", f"/api/api-keys/{kid}/revoke", cookie=cookie)
expect(st == 200 and body.get("already_revoked") is False, "revoke 200", body)

st, body, _ = call("GET", "/api/dashboard", bearer=key)
expect(st == 401, "revoked key 401", st)

st, body, _ = call("POST", f"/api/api-keys/{kid}/revoke", cookie=cookie)
expect(st == 200 and body.get("already_revoked") is True, "revoke idempotent", body)

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken post-revoke: {body}"
print(f"ok - audit chain valid after lifecycle ({body['entries']} entries)")

print("LIVE APIKEY CHECK PASS")
