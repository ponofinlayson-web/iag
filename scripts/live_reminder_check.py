"""Live reminder-queue check against the running stack (real Postgres path).

Proves: enqueue-on-start writes outbox rows with resolved recipients; the
in-replica worker drains them (log-only dev delivery); the read-only API
exposes rows; cancel blocks send; audit chain stays valid.
"""
import io
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
POLL_S = 5
DEADLINE_S = 120
_COOKIE = ""


def call(method, path, body=None, cookie=None, raw=None):
    req = urllib.request.Request(BASE + path, method=method)
    if cookie or _COOKIE:
        req.add_header("Cookie", cookie or _COOKIE)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if raw is not None:
        data = raw
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
_COOKIE = cookie

# unique tag per run so re-runs on a shared stack never collide
tag = f"live-{int(time.time())}"
BOUNDARY = "iagprobe7351"


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


def upload(path, filename, content, cookie=cookie):
    req = urllib.request.Request(BASE + path, method="POST")
    req.add_header("Cookie", cookie)
    req.add_header("Content-Type", f"multipart/form-data; boundary={BOUNDARY}")
    with urllib.request.urlopen(req, multipart([("file", filename, content)])) as r:
        return r.status, json.loads(r.read())


ident_csv = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    f"E-{tag},u{int(time.time())},live-{tag}@x.io,Liv,Er,Engineering,\n"
).encode()

st, body = upload("/api/identities/import", "people.csv", ident_csv)
print(f"identities import: {st} {body}")
assert st == 200 and body["created"] >= 1, f"identities import {st}: {body}"

st, body, _ = call("POST", "/api/sources", {
    "name": f"live-rem-{tag}", "source_type": "csv",
    "owner_employee_id": "E-ADMIN"})
assert st == 200, f"source create {st}: {body}"
sid = body["id"]

access_csv = f"account,entitlement,privilege\nliveu,Live Ent {tag},high\n".encode()
st, body = upload(f"/api/sources/{sid}/upload", "access.csv", access_csv)
assert st == 200, f"upload {st}: {body}"
st, body, _ = call("POST", f"/api/sources/{sid}/accounts/bulk-link",
                   {"match_on": "username"})
assert st == 200, f"bulk-link {st}: {body}"

st, body, _ = call("POST", "/api/campaigns", {
    "name": f"rem-live-{tag}", "review_mode": "source_owner"})
assert st == 200, f"campaign create {st}: {body}"
cid = body["id"]
for step in ("preview", "stage", "start"):
    st, body, _ = call("POST", f"/api/campaigns/{cid}/{step}")
    assert st == 200, f"{step} {st}: {body}"
print(f"campaign {cid} started: {body}")

st, body, _ = call("GET", f"/api/reminders/campaigns/{cid}", cookie=cookie)
assert st == 200, f"campaign reminders {st}: {body}"
rows = body["items"]
assert len(rows) == 1, f"expected 1 outbox row (liveu account, admin reviewer), got {len(rows)}"
assert rows[0]["recipient"], f"recipient not resolved: {rows[0]}"
print(f"outbox row enqueued: recipient={rows[0]['recipient']} status={rows[0]['status']}")

deadline = time.time() + DEADLINE_S
sent = False
while time.time() < deadline:
    st, body, _ = call("GET", f"/api/reminders/campaigns/{cid}", cookie=cookie)
    assert st == 200
    if all(r["status"] == "sent" for r in body["items"]):
        sent = True
        break
    time.sleep(POLL_S)
assert sent, f"worker did not drain rows: {[(r['recipient'], r['status'], r['last_error']) for r in body['items']]}"
print(f"all rows SENT within {DEADLINE_S}s (worker, log-only delivery)")
for r in body["items"]:
    assert r["sent_at"], "sent_at missing"

# cancel path on a second campaign
st, body, _ = call("POST", "/api/campaigns", {
    "name": f"rem-cancel-{tag}", "review_mode": "source_owner"})
cid2 = body["id"]
for step in ("preview", "stage", "start"):
    st, body, _ = call("POST", f"/api/campaigns/{cid2}/{step}")
    assert st == 200, f"{step} {st}: {body}"
st, body, _ = call("POST", f"/api/campaigns/{cid2}/cancel")
assert st == 200, f"cancel {st}: {body}"
st, body, _ = call("GET", f"/api/reminders/campaigns/{cid2}", cookie=cookie)
assert all(r["status"] == "cancelled" for r in body["items"]), body["items"]
print("cancel path: rows cancelled, never sent")

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"audit chain valid, {body['entries']} entries")
print("LIVE REMINDER CHECK PASS")
