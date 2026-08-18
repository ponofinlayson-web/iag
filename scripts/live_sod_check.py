"""Live SoD endpoint check against the running stack (real Postgres path)."""
import os, sys, urllib.request, json

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")


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
        return e.code, json.loads(e.read() or b"{}"), ""


st, body, cookie = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
cookie = cookie.split(";")[0] if cookie else ""
assert cookie, "no session cookie"

st, body, _ = call("GET", "/api/sod/rules", cookie=cookie)
assert st == 200, f"rules list {st}: {body}"
print(f"GET /api/sod/rules OK - {len(body['items'])} rules")

st, body, _ = call("POST", "/api/sod/rules", {
    "name": "__live_probe__", "entitlement_a_id": 1, "entitlement_b_id": 2}, cookie=cookie)
print(f"POST /api/sod/rules (expect 400 unknown entitlement on fresh stack): {st} {body.get('detail', '')}")

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"audit chain valid, {body['entries']} entries")
print("LIVE SOD CHECK PASS")
