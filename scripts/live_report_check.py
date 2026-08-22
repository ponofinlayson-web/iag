"""Live campaign-report check against the running stack (real Postgres path).

Proves feature 5 part 2 end to end: seed identity + source + accounts,
start a campaign, decide 2 of 3 reviews (one revoke with the mandatory
comment), then verify the report JSON shape, the streamed report.csv, and
that nginx serves the SPA shell for /campaigns/:id/report (rendering is a
frontend concern - vite build + TSC already gated it).

Uses its own unique tag; safe to re-run. Start AFTER live_risk_check.
"""
import io
import csv as csv_mod
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

tag = f"rp{int(time.time())}"
ts = int(time.time())

# --- seed: identity (with manager), source, 3 distinct accounts ------------
ident_csv = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    f"E-{tag},rep{ts},rep-{tag}@x.io,Ree,Port,Finance,\n"
).encode()
st, body = upload("/api/identities/import", "people.csv", ident_csv)
assert st == 200 and body["created"] == 1, f"identities import {st}: {body}"

st, body, _ = call("POST", "/api/sources", {
    "name": f"report-live-{tag}", "source_type": "csv",
    "owner_employee_id": "E-ADMIN"})
assert st == 200, f"source create {st}: {body}"
sid = body["id"]

acc_csv = (
    "account,entitlement,privilege\n"
    f"rep{ts}-a1,EntA-{tag},high\n"
    f"rep{ts}-a2,EntB-{tag},moderate\n"
    f"rep{ts}-a3,EntC-{tag},low\n"
).encode()
st, body = upload(f"/api/sources/{sid}/upload", "access.csv", acc_csv)
assert st == 200 and body["accounts_created"] == 3, f"upload {st}: {body}"
print("ok - seeded 1 identity, 3 accounts")

st, body, _ = call("POST", f"/api/sources/{sid}/accounts/bulk-link",
                   {"match_on": "username"})
assert st == 200, f"bulk-link {st}: {body}"
# bulk-link matches username: exact-match accounts only. Link the rest.
st, body, _ = call("GET", f"/api/sources/{sid}/accounts?linked=unlinked&page_size=100")
assert st == 200, f"accounts list {st}: {body}"
if body["total"]:
    st, ibody, _ = call("GET", f"/api/identities?q=rep{ts}")
    assert st == 200 and ibody["total"] == 1, f"find identity {st}: {ibody}"
    iid = ibody["items"][0]["id"]
    for it in body["items"]:
        st2, _, _ = call("PUT", f"/api/sources/{sid}/accounts/{it['id']}/link",
                         {"identity_id": iid})
        assert st2 == 200, f"link {it['id']} {st2}"
print("ok - accounts linked")

# --- campaign lifecycle: create -> preview -> stage -> start ---------------
st, body, _ = call("POST", "/api/campaigns", {
    "name": f"report-live-{tag}", "review_mode": "source_owner"})
assert st == 200, f"campaign create {st}: {body}"
cid = body["id"]
for step in ("preview", "stage", "start"):
    st, body, _ = call("POST", f"/api/campaigns/{cid}/{step}")
    assert st == 200, f"campaign {step} {st}: {body}"
print(f"ok - campaign {cid} started")

# --- decisions: approve a1, revoke a2 (comment), leave a3 pending ----------
st, body, _ = call("GET", "/api/reviews/queue")
assert st == 200 and body["total"] >= 3, f"queue {st}: {body}"
mine = [it for it in body["items"] if it["campaign_id"] == cid]
assert len(mine) == 3, f"expected 3 reviews in campaign, got {len(mine)}"

by_acct = {it["account_value"]: it["id"] for it in mine}
rid_a1 = by_acct[f"rep{ts}-a1"]
rid_a2 = by_acct[f"rep{ts}-a2"]

st, body, _ = call("POST", f"/api/reviews/{rid_a1}/submit",
                   {"decision": "approve"})
assert st == 200, f"approve {st}: {body}"
st, body, _ = call("POST", f"/api/reviews/{rid_a2}/submit",
                   {"decision": "revoke", "comments": f"revoke-reason-{tag}"})
assert st == 200, f"revoke {st}: {body}"
print("ok - 2 of 3 decided (1 approve, 1 revoke w/ comment)")

# --- own risk run so the report risk block is non-null ---------------------
st, body, _ = call("POST", "/api/risk/runs")
assert st == 202, f"risk run {st}: {body}"
risk_run = body["run_id"]

# --- report JSON -----------------------------------------------------------
st, rep, _ = call("GET", f"/api/campaigns/{cid}/report")
assert st == 200, f"report {st}: {rep}"
expect(rep["campaign"]["id"] == cid and rep["campaign"]["status"] == "active",
       "report header", rep["campaign"])
expect(rep["completion"]["total"] == 3 and rep["completion"]["completed"] == 2
       and rep["completion"]["pending"] == 1,
       "completion 2/3 done", rep["completion"])
expect(rep["decisions"] == {"approved": 1, "revoked": 1, "pending": 1},
       "decisions by status", rep["decisions"])
wl = rep["reviewer_workload"]
expect(len(wl) == 1 and wl[0]["assigned"] == 3 and wl[0]["approved"] == 1
       and wl[0]["revoked"] == 1 and wl[0]["pending"] == 1,
       "reviewer workload row", wl)
rv = rep["revocations"]
expect(len(rv) == 1 and rv[0]["account"] == f"rep{ts}-a2"
       and rv[0]["comment"] == f"revoke-reason-{tag}",
       "revocation detail w/ mandatory comment", rv)
expect(rep["risk"] is not None and rep["risk"]["run_id"] == risk_run,
       "risk block from latest run", rep.get("risk"))
expect(rep["risk"]["scored_in_campaign"] == 1, "risk scored 1 campaign identity",
       rep["risk"])
print(f"ok - report JSON verified (risk block run {risk_run[:8]})")

# --- report.csv ------------------------------------------------------------
req = urllib.request.Request(BASE + f"/api/campaigns/{cid}/report.csv")
req.add_header("Cookie", COOKIE)
with urllib.request.urlopen(req) as r:
    assert r.status == 200, f"csv {r.status}"
    csv_text = r.read().decode()
rows = list(csv_mod.reader(io.StringIO(csv_text)))
expect(rows[0][:4] == ["identity", "employee_id", "source", "entitlement"],
       "csv header", rows[0])
expect(len(rows) == 4, "csv rows = header + 3 decisions", len(rows))
dec_col = rows[0].index("decision")
by_decision = {row[dec_col]: row for row in rows[1:]}
expect(set(by_decision) == {"approved", "revoked", "pending"},
       "csv carries all three decisions", sorted(by_decision))
comment_col = rows[0].index("comment")
expect(by_decision["revoked"][comment_col] == f"revoke-reason-{tag}",
       "csv revoke comment present", by_decision["revoked"][comment_col])
print("ok - report.csv streamed and verified")

# --- decision rows match metrics ------------------------------------------
st, met, _ = call("GET", f"/api/campaigns/{cid}/metrics")
assert st == 200, f"metrics {st}: {met}"
expect(met["by_status"] == rep["decisions"], "csv decisions == metrics decisions",
       (met["by_status"], rep["decisions"]))

# --- SPA shell smoke (nginx serves frontend for the report route) ----------
req = urllib.request.Request(BASE + f"/campaigns/{cid}/report")
with urllib.request.urlopen(req) as r:
    html = r.read().decode("utf-8", "replace")
expect('<div id="root">' in html and "<title>IAG</title>" in html,
       "SPA shell served for /campaigns/:id/report")
print("ok - SPA shell served (print view is a frontend concern)")

# --- audit chain intact ----------------------------------------------------
st, body, _ = call("GET", "/api/audit/verify")
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"ok - audit chain valid ({body['entries']} entries)")

print("LIVE REPORT CHECK PASS")
