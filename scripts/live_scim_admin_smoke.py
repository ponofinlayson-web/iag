"""Live phase-C smoke: management surface + enforce rules via nginx 8090.

Idempotent: resets SCIM settings FIRST (disabled, no token) so a failed prior
run never leaves enabled=true + a stale hash.
"""
import json
import os
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
FAILED = []


def req(path, method="GET", body=None, token=None, cookies=None, raw=False):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    if cookies:
        r.add_header("Cookie", cookies)
    data = json.dumps(body).encode() if body is not None else None
    try:
        resp = urllib.request.urlopen(r, data)
        code, text, hdrs = resp.status, resp.read().decode(), resp.headers
    except urllib.error.HTTPError as e:
        code, text, hdrs = e.code, e.read().decode(), e.headers
    if raw:
        return code, text, hdrs
    try:
        return code, json.loads(text) if text else None
    except json.JSONDecodeError:
        return code, text


def check(name, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond:
        FAILED.append(name)


# --- login (system_admin manages the surface) ---
pw = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
code, text, hdrs = req("/api/auth/login", "POST", {"username": "admin", "password": pw}, raw=True)
check("admin login", code == 200, f"code={code}")
cookie = None
sc = hdrs.get("Set-Cookie", "") if hdrs else ""
if sc:
    cookie = sc.split(";")[0]
check("session cookie obtained", bool(cookie))

code, _ = req("/api/scim/config", cookies=cookie)
check("config GET as admin", code == 200, f"code={code}")

code, _ = req("/api/scim/token", "POST", cookies=cookie)
check("token POST before enable", code in (200, 201), f"code={code}")

code, body = req("/api/scim/config", "PUT", {"enabled": False}, cookies=cookie)
check("config PUT disabled (reset)", code == 200, f"code={code}")
code, body = req("/api/scim/token", "DELETE", cookies=cookie)
check("token DELETE (reset)", code == 200, f"code={code}")

code, body = req("/api/scim/config", cookies=cookie)
check("reset state: disabled, no token", code == 200 and body["enabled"] is False
      and body["token_prefix"] is None, str(body))

# --- enable + generate ---
code, body = req("/api/scim/config", "PUT", {"enabled": True}, cookies=cookie)
check("enable", code == 200 and body["enabled"] is True, f"code={code}")

code, body = req("/api/scim/token", "POST", cookies=cookie)
check("token generate", code in (200, 201) and body.get("token", "").startswith("iag_scim_"), f"code={code}")
tok1 = body["token"]

code, body = req("/api/scim/config", cookies=cookie)
check("config shows prefix, not hash", code == 200 and body["token_prefix"]
      and body["token_prefix"] in tok1 and "token_hash" not in body, str(body)[:120])

code, body = req("/api/scim/v2/Users", token=tok1)
check("protocol list behind bearer", code == 200, f"code={code}")

# --- rotate kills old ---
code, body = req("/api/scim/token", "POST", cookies=cookie)
tok2 = body["token"]
check("rotate returns new", tok2 != tok1)
code, _ = req("/api/scim/v2/Users", token=tok1)
check("old bearer dead after rotate", code == 401, f"code={code}")
code, _ = req("/api/scim/v2/Users", token=tok2)
check("new bearer works", code == 200, f"code={code}")

# --- enforce rule CRUD via live API ---
rule = {"name": "phasec-smoke-enforce", "action": "enforce",
        "target": "disable_account", "entitlement_pattern": "^Smoke"}
code, body = req("/api/remediation/rules", "POST", rule, cookies=cookie)
check("enforce rule create", code == 200, f"code={code} {str(body)[:80]}")
rid = body.get("id") if isinstance(body, dict) else None

code, body = req("/api/remediation/rules", cookies=cookie)
row = next((x for x in body["items"] if x["id"] == rid), None) if code == 200 else None
check("rule row has target + approval ON", row and row["target"] == "disable_account"
      and row["require_approval"] is True, str(row)[:100] if row else "missing")

code, _ = req("/api/remediation/rules", "POST", {**rule, "name": "bad-target",
                                                 "target": "nuke"}, cookies=cookie)
check("bad target rejected 400", code == 400, f"code={code}")

code, _ = req("/api/remediation/rules", "POST", {**rule, "name": "enforce-webhook",
                                                 "webhook_url": "https://x.io/h"}, cookies=cookie)
check("enforce+webhook rejected 400", code == 400, f"code={code}")

code, _ = req("/api/remediation/settings", "PUT", {"enabled": True,
                                                   "default_action": "enforce",
                                                   "require_approval_for_high_risk": True},
              cookies=cookie)
check("default_action=enforce rejected 400", code == 400, f"code={code}")

# --- revoke closes surface; enabled stays ---
code, body = req("/api/scim/token", "DELETE", cookies=cookie)
check("revoke ok", code == 200 and body.get("ok") is True, str(body))
code, _ = req("/api/scim/v2/Users", token=tok2)
check("surface 503 after revoke", code == 503, f"code={code}")
code, body = req("/api/scim/config", cookies=cookie)
check("enabled stays true after revoke", body["enabled"] is True, str(body))

# --- cleanup: rule delete + disable ---
if rid:
    code, _ = req(f"/api/remediation/rules/{rid}", "DELETE", cookies=cookie)
    check("rule delete", code in (200, 204), f"code={code}")
code, _ = req("/api/scim/config", "PUT", {"enabled": False}, cookies=cookie)
check("final disable", code == 200, f"code={code}")

# --- audit chain ---
code, body = req("/api/audit/verify", cookies=cookie)
check("audit chain verifies", code == 200 and body["valid"] is True, f"code={code}")

print()
if FAILED:
    print(f"SMOKE FAILED: {len(FAILED)} leg(s): {FAILED}")
    raise SystemExit(1)
print("SMOKE PASS: all legs green")
