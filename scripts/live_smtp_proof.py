"""Live SMTP-branch proof against the running stack + aiosmtpd sink.

Proves: enqueue renders templates; worker takes the SMTP path (not log-only);
the sink receives the rendered message (subject w/ campaign name, body w/
review URL + greeting); outbox rows finalize to sent; audit chain valid.

Preconditions: sink on host :1025 (scripts/smtp_sink.py), stack recreated
with IAG_SMTP_HOST=host.docker.internal in .env.
"""
import io
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
SINK_LOG = os.environ.get("SINK_LOG", "smtp_sink_log.jsonl")
DEADLINE_S = 120
COOKIE = ""

PEOPLE = ("employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
          "E-SP1,spalice,spalice@x.io,Alice,Andrews,Engineering,\n"
          "E-SP2,spbob,spbob@x.io,Bob,Brown,Engineering,E-SP1\n")
ACCOUNTS = "account,entitlement,privilege\nspalice,Eng Admin,high\nspbob,Read Only,low\n"


def call(method, path, body=None, raw=None):
    global COOKIE
    req = urllib.request.Request(BASE + path, method=method)
    if COOKIE:
        req.add_header("Cookie", COOKIE)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if raw is not None:
        data = raw
    try:
        with urllib.request.urlopen(req, data) as r:
            sc = r.headers.get("Set-Cookie", "")
            if sc:
                COOKIE = sc.split(";")[0]
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def upload(path, name, content):
    boundary = "----iagproof"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{name}\"\r\nContent-Type: text/csv\r\n\r\n"
            f"{content}\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(BASE + path, method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if COOKIE:
        req.add_header("Cookie", COOKIE)
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


st, _ = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}"

st, _ = upload("/api/identities/import", "people.csv", PEOPLE)
assert st == 200, f"import {st}"
st, src = call("POST", "/api/sources",
               {"name": f"SmtpSrc-{int(time.time())}", "source_type": "csv",
                "owner_employee_id": "E-ADMIN"})
assert st == 200, f"source {st}: {src}"
sid = src["id"]
st, _ = upload(f"/api/sources/{sid}/upload", "accounts.csv", ACCOUNTS)
assert st == 200, f"upload {st}"
st, _ = call("POST", f"/api/sources/{sid}/accounts/bulk-link", {"match_on": "username"})
assert st == 200, f"link {st}"

campaign_name = f"SmtpProof-{int(time.time())}"
st, c = call("POST", "/api/campaigns",
             {"name": campaign_name, "review_mode": "source_owner"})
assert st == 200, f"campaign {st}: {c}"
cid = c["id"]
st, _ = call("POST", f"/api/campaigns/{cid}/stage")
assert st == 200, f"stage {st}"
st, r = call("POST", f"/api/campaigns/{cid}/start")
assert st == 200, f"start {st}: {r}"
expected = r["reviews_created"]  # live DB carries history; never hardcode counts

print(f"campaign {cid} started; polling outbox...")
rows = []
deadline = time.time() + DEADLINE_S
while time.time() < deadline:
    st, page = call("GET", f"/api/reminders/outbox?campaign_id={cid}")
    assert st == 200, f"outbox {st}"
    rows = page["items"]
    if rows and all(x["status"] == "sent" for x in rows):
        break
    time.sleep(5)
assert rows and all(x["status"] == "sent" for x in rows), \
    f"not all sent: {[(x['id'], x['status'], x['last_error']) for x in rows]}"

with open(SINK_LOG, encoding="utf-8") as f:
    msgs = [json.loads(line) for line in f]
cname = f"campaign '{campaign_name}'"
mine = [m for m in msgs if cname in m["data"]]
assert len(mine) == expected, f"sink saw {len(mine)} {campaign_name} messages, want {expected}"
import re
for m in mine:
    assert f"/reviews?campaign={cid}" in m["data"], "body missing review URL"
    # live bootstrap admin's name differs from the test fixture's; assert shape
    assert re.search(r"^Hello .+,\r?$", m["data"], re.MULTILINE), \
        "body missing rendered greeting line"

st, v = call("GET", "/api/audit/verify")
assert st == 200 and v["valid"] is True, f"audit verify {st}: {v}"

print(f"PASS: {expected} emails through real SMTP -> sink; rendered subject/URL/"
      "greeting; outbox sent; audit chain valid")
