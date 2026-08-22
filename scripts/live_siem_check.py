"""Live SIEM feed check against the running stack (real Postgres path).

Proves feature 5 part 3 end to end, as an external SIEM would consume it:
1. Admin (cookie) creates an auditor-role API key.
2. Bearer key walks /api/audit/feed from after_id=0 in small pages -
   concatenation must equal the audit CSV export row-for-row (three-way
   consistency: feed == export == chain), hashes recompute client-side
   walking pages (the transportable-evidence proof), X-IAG-Last-Id /
   X-IAG-Head honored.
3. /feed/stats chain_valid true, last_id matches the walk's end.
4. report_viewer key is 403 on the feed (AuditViewer = auditor only).
5. NO tamper is performed on the live chain (spec E.4); revoke the key.

Run LAST (after risk + report checks) so the walk covers their entries.
"""
import csv as csv_mod
import hashlib
import io
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


def pull(bearer, after_id, limit):
    """GET one feed page; returns (status, rows, last_id_header, head_header)."""
    req = urllib.request.Request(
        BASE + f"/api/audit/feed?after_id={after_id}&limit={limit}")
    req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
            rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
            return r.status, rows, r.headers.get("X-IAG-Last-Id"), r.headers.get("X-IAG-Head")
    except urllib.error.HTTPError as e:
        return e.code, [], None, None


st, body, sc = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
cookie = (sc.split(";")[0] if sc else "").strip()
assert cookie, "no session cookie"
print("ok - admin login (cookie)")

# --- 1. auditor key --------------------------------------------------------
name = f"siem-live-{os.urandom(3).hex()}"
st, body, _ = call("POST", "/api/api-keys",
                   {"name": name, "role": "auditor"}, cookie=cookie)
assert st == 201, f"create auditor key {st}: {body}"
aud_key, kid = body["key"], body["id"]
print(f"ok - auditor key {body['key_prefix']}... created")

# report_viewer key for the guard check
st, body, _ = call("POST", "/api/api-keys",
                   {"name": name + "-rv", "role": "report_viewer"}, cookie=cookie)
assert st == 201, f"create rv key {st}: {body}"
rv_key, rv_kid = body["key"], body["id"]

# --- 2. walk the feed in small pages, then catch up to head ----------------
# (a background worker can append between walk and export; a real poller
# pages forward to the advertised head instead of failing)
PAGE = 25
walk_rows = []
after = 0
pages = 0
last_hdr = None
head_hdr = None
while True:
    st, rows, last_hdr, head_hdr = pull(aud_key, after, PAGE)
    assert st == 200, f"feed page {pages} {st}"
    if not rows:
        break
    walk_rows.extend(rows)
    expect(int(last_hdr) == rows[-1]["id"], f"page {pages}: Last-Id = last row id")
    after = rows[-1]["id"]
    pages += 1
    if len(rows) < PAGE:
        break
expect(pages >= 2, f"walk covered >= 2 pages ({pages})", pages)
expect(len(walk_rows) >= 50, f"walked {len(walk_rows)} entries", len(walk_rows))
print(f"ok - walked {len(walk_rows)} entries in {pages} pages")

for _ in range(5):  # catch-up bound
    st, stats_now, _ = call("GET", "/api/audit/feed/stats", bearer=aud_key)
    assert st == 200, f"stats {st}: {stats_now}"
    if stats_now["last_id"] <= walk_rows[-1]["id"]:
        break
    st, rows, last_hdr, head_hdr = pull(aud_key, walk_rows[-1]["id"], 5000)
    assert st == 200 and rows, f"catch-up page {st}"
    walk_rows.extend(rows)
    print(f"ok - caught up {len(rows)} new entries (background writer)")
else:
    raise AssertionError("feed head keeps advancing; stack too busy for proof")

# ids strictly ascending, no gaps/dupes
ids = [r["id"] for r in walk_rows]
expect(ids == sorted(ids) and len(ids) == len(set(ids)), "ids strictly ascending")

# --- client-side chain recompute (transportable evidence) ------------------
prev = "0" * 64
for row in walk_rows:
    if isinstance(row["details"], str):
        details_str = row["details"]
    else:
        details_str = json.dumps(row["details"], sort_keys=True,
                                 separators=(",", ":"), default=str)
    payload = {
        "action": row["action"],
        "actor_id": row["actor_id"],
        "actor_username": row["actor_username"],
        "details": details_str,
        "entity_id": row["entity_id"],
        "entity_type": row["entity_type"],
        "ts": row["ts"] + "+00:00",
    }
    material = prev + json.dumps(payload, sort_keys=True,
                                 separators=(",", ":"), default=str)
    digest = hashlib.sha256(material.encode()).hexdigest()
    assert digest == row["record_hash"], (
        f"hash mismatch at id {row['id']}: {digest} != {row['record_hash']}")
    assert row["prev_hash"] == prev, f"prev_hash break at id {row['id']}"
    prev = row["record_hash"]
expect(head_hdr == prev, "X-IAG-Head equals recomputed chain head")
print(f"ok - client-side chain recompute: {len(walk_rows)} entries verified")

# --- three-way consistency: feed == CSV export == server chain -------------
req = urllib.request.Request(BASE + "/api/audit/export")
req.add_header("Cookie", cookie)
with urllib.request.urlopen(req) as r:
    export_text = r.read().decode()
export_rows = list(csv_mod.reader(io.StringIO(export_text)))[1:]
expect(len(export_rows) == len(walk_rows),
       f"feed rows ({len(walk_rows)}) == export rows ({len(export_rows)})")
for er, fr in zip(export_rows, walk_rows):
    assert int(er[0]) == fr["id"], f"id mismatch {er[0]} != {fr['id']}"
    assert er[2] == fr["actor_username"], f"actor mismatch at {fr['id']}"
    assert er[3] == fr["action"], f"action mismatch at {fr['id']}"
    assert er[7] == fr["record_hash"], f"hash mismatch at {fr['id']}"
print("ok - feed == CSV export row-for-row (id/actor/action/hash)")

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"server chain invalid: {body}"
expect(body["head"] == prev, "server verify head == client recompute head")
print(f"ok - server chain valid ({body['entries']} entries, heads match)")

# --- 3. /feed/stats --------------------------------------------------------
st, body, _ = call("GET", "/api/audit/feed/stats", bearer=aud_key)
assert st == 200, f"stats {st}: {body}"
expect(body["chain_valid"] is True, "stats chain_valid true", body)
expect(body["last_id"] == walk_rows[-1]["id"], "stats last_id == walk end", body)
expect(body["chain_head"] == prev, "stats chain_head == recomputed head")
expect(body["total_entries"] == len(walk_rows), "stats total == walked count", body)
print(f"ok - feed/stats: {body['total_entries']} entries, head matches walk")

# --- 4. guard: report_viewer key 403, write choked -------------------------
st, rows, _, _ = pull(rv_key, 0, 1)
expect(st == 403, "report_viewer key 403 on feed", st)
st, body, _ = call("POST", "/api/risk/runs", bearer=aud_key)
expect(st == 403, "key cannot trigger risk run", st)
print("ok - guards: rv-key feed 403, key write 403")

# --- 5. revoke + chain still valid ----------------------------------------
st, body, _ = call("POST", f"/api/api-keys/{kid}/revoke", cookie=cookie)
expect(st == 200 and body.get("already_revoked") is False, "revoke auditor key", body)
st, body, _ = call("POST", f"/api/api-keys/{rv_kid}/revoke", cookie=cookie)
expect(st == 200, "revoke rv key", body)
st, rows, _, _ = pull(aud_key, 0, 1)
expect(st == 401, "revoked key 401 on feed", st)

st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken: {body}"
print(f"ok - audit chain valid after lifecycle ({body['entries']} entries)")

print("LIVE SIEM CHECK PASS")
