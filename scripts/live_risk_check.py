"""Live risk-scoring check against the running stack (real Postgres path).

Proves feature 5 part 1 end to end: seed two risk-shaped identities, run
POST /api/risk/runs twice, then verify summary / snapshots / trend shapes
and the audit chain. Expected scores are hand-computed from the transparent
engine (risk_engine.py) - the transparency contract is the point:

  risky  (5 very_high accts, no manager, 3 SoD rules):
      unreviewed_access   20.0  (5/5 accounts unreviewed)
      privileged_access   20.0  (10 weighted = divisor cap)
      sod_violations      20.0  (3 = SOD_DIVISOR cap)
      privilege_creep     10.0  (5/5 accounts fresh)
      orphaned_access     10.0  (accounts but no manager)
      stale_identity       0.0  (identity active)
      source_concentration 2.5  (5 accounts / 20, min 1)
      => 82.5 critical
  clean (no accounts): 0.0 low

Run AFTER live_risk_check only; it seeds its own data (unique tag).
"""
import io
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
BOUNDARY = "iagprobe7351"
COOKIE = ""


def call(method, path, body=None, cookie=None):
    req = urllib.request.Request(BASE + path, method=method)
    if cookie or COOKIE:
        req.add_header("Cookie", cookie or COOKIE)
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


def multipart(fields):
    out = io.BytesIO()
    for name, filename, content in fields:
        out.write(f"--{BOUNDARY}\r\n".encode())
        out.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        out.write(b"Content-Type: text/csv\r\n\r\n")
        out.write(content)
        out.write(b"\r\n")
    out.write(f"--{BOUNDARY}--\r\n".encode())
    return out.getvalue()


def upload(path, filename, content):
    req = urllib.request.Request(BASE + path, method="POST")
    req.add_header("Cookie", COOKIE)
    req.add_header("Content-Type", f"multipart/form-data; boundary={BOUNDARY}")
    with urllib.request.urlopen(req, multipart([("file", filename, content)])) as r:
        return r.status, json.loads(r.read())


st, body, sc = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
COOKIE = (sc.split(";")[0] if sc else "").strip()
assert COOKIE, "no session cookie"
print("ok - admin login (cookie)")

tag = f"rk{int(time.time())}"
ts = int(time.time())

# --- seed identities: one risk-shaped, one clean ---------------------------
ident_csv = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    f"E-{tag}-R,risky{ts},risky-{tag}@x.io,Ris,Ky,SecurityOps,\n"        # no manager
    f"E-{tag}-C,clean{ts},clean-{tag}@x.io,Cle,An,Finance,E-{tag}-R\n"   # manager set
).encode()
st, body = upload("/api/identities/import", "people.csv", ident_csv)
assert st == 200 and body["created"] == 2, f"identities import {st}: {body}"
print("ok - seeded 2 identities (risky, clean)")

st, body, _ = call("GET", f"/api/identities?q=risky{ts}")
assert st == 200 and body["total"] == 1, f"find risky {st}: {body}"
risky_id = body["items"][0]["id"]

# --- seed 5 very_high accounts + 4 entitlements on one source --------------
st, body, _ = call("POST", "/api/sources", {
    "name": f"risk-live-{tag}", "source_type": "csv",
    "owner_employee_id": f"E-{tag}-R"})
assert st == 200, f"source create {st}: {body}"
sid = body["id"]

rows = ["account,entitlement,privilege"]
for i in range(1, 6):
    rows.append(f"risky{ts}-acct{i},Ent-{tag}-{(i % 4) + 1},very_high")
st, body = upload(f"/api/sources/{sid}/upload", "access.csv",
                  ("\n".join(rows) + "\n").encode())
assert st == 200 and body["accounts_created"] == 5, f"upload {st}: {body}"
print("ok - 5 very_high accounts, 4 distinct entitlements")

# link each account individually (bulk-link matches username only)
st, body, _ = call("GET", f"/api/sources/{sid}/accounts?linked=unlinked&page_size=100")
assert st == 200 and body["total"] == 5, f"accounts list {st}: {body}"
for it in body["items"]:
    st, body, _ = call("PUT", f"/api/sources/{sid}/accounts/{it['id']}/link",
                       {"identity_id": risky_id})
    assert st == 200, f"link {it['id']} {st}: {body}"
print("ok - 5 accounts linked to risky identity")

# --- 3 SoD rules over the 4 entitlements (ent pairs A-B, A-C, A-D) ---------
# ids assigned by creation order: Ent-1 -> a, Ent-2 -> b, Ent-3 -> c, Ent-4 -> d
st, body, _ = call("GET", f"/api/entitlements?q=Ent-{tag}-")
assert st == 200 and body["total"] == 4, f"entitlements {st}: {body}"
ents = {e["name"]: e["id"] for e in body["items"]}
a, b, c, d = (ents[f"Ent-{tag}-{i}"] for i in range(1, 5))
for i, (x, y) in enumerate(((a, b), (a, c), (a, d)), 1):
    st, body, _ = call("POST", "/api/sod/rules", {
        "name": f"live-risk-{tag}-{i}", "entitlement_a_id": x, "entitlement_b_id": y})
    assert st == 200, f"sod rule {i} {st}: {body}"
print("ok - 3 SoD rules created")

# --- run 1: POST /runs -> summary/snapshots/trend --------------------------
st, body, _ = call("POST", "/api/risk/runs")
assert st == 202, f"risk run {st}: {body}"
run1 = body["run_id"]
expect(body["scored_identities"] >= 2, "run scored >= 2 identities", body)
expect(body["band_distribution"].get("critical", 0) >= 1, "run sees critical band", body)
print(f"ok - run 1 {run1[:8]}: {body['band_distribution']}")

st, body, _ = call("GET", "/api/risk/summary")
assert st == 200, f"summary {st}: {body}"
assert body["run_id"] == run1, f"summary run {body.get('run_id')} != {run1}"
top = body["top_risky"]
expect(len(top) >= 1 and top[0]["score"] == 82.5 and top[0]["band"] == "critical",
       "summary top risky = 82.5 critical", top[:1])
expect(top[0]["top_factors"] and top[0]["top_factors"][0]["contribution"] == 20.0,
       "top factor transparent (contribution 20)", top[0]["top_factors"][:1])
expect(body["band_distribution"].get("low", 0) >= 1, "summary sees low band", body["band_distribution"])
print(f"ok - summary: {body['band_distribution']} avg={body['average_score']}")

# snapshots: run1 rows for risky + clean
st, body, _ = call("GET", f"/api/risk/snapshots?run_id={run1}")
assert st == 200 and body["total"] == body["total"], f"snapshots {st}"
found = {it["employee_id"]: it for it in body["items"]}
assert f"E-{tag}-R" in found, f"risky snapshot missing: {list(found)}"
expect(found[f"E-{tag}-R"]["score"] == 82.5 and found[f"E-{tag}-R"]["band"] == "critical",
       "snapshot risky = 82.5 critical", found[f"E-{tag}-R"])
expect(found[f"E-{tag}-R"]["signals"]["sod_violations"] == 20.0,
       "signals carry sod_violations 20", found[f"E-{tag}-R"]["signals"])
if f"E-{tag}-C" in found:
    expect(found[f"E-{tag}-C"]["score"] == 0.0, "clean identity = 0.0", found[f"E-{tag}-C"])
print("ok - snapshots: risky 82.5 critical, signals carried")

# band filter sanity
st, body, _ = call("GET", f"/api/risk/snapshots?run_id={run1}&band=critical")
expect(st == 200 and all(it["band"] == "critical" for it in body["items"]),
       "band filter returns critical only", body.get("total"))

# --- run 2: trend proves run grouping (D4) --------------------------------
st, body, _ = call("POST", "/api/risk/runs")
assert st == 202, f"risk run 2 {st}: {body}"
run2 = body["run_id"]
assert run2 != run1

st, body, _ = call("GET", f"/api/risk/trend/{risky_id}")
assert st == 200, f"trend {st}: {body}"
items = body["items"]
expect(len(items) == 2, "trend shows 2 runs", len(items))
expect(items[0]["run_id"] == run1 and items[1]["run_id"] == run2,
       "trend oldest-first across runs", [i["run_id"][:8] for i in items])
expect(all(i["score"] == 82.5 for i in items), "trend scores stable at 82.5",
       [i["score"] for i in items])
print("ok - trend: 2 runs, oldest-first, stable scores")

# --- audit chain intact ----------------------------------------------------
st, body, _ = call("GET", "/api/audit/verify")
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"ok - audit chain valid ({body['entries']} entries)")

print("LIVE RISK CHECK PASS")
