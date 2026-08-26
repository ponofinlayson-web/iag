"""Live remediation proof: full revoke->action->delivery loop on the real stack.

Legs:
  1. email leg — notify_owner delivered to the smtp_sink container; the
     in-replica remediation worker does the sending (real SMTP client).
  2. webhook leg — action POSTed to a local HTTP sink we run in this
     script; the worker in the container must reach the host.

Exit code 0 = PASS. Reads env IAG_BASE (default http://localhost:8090).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

BASE = os.environ.get("IAG_BASE", "http://localhost:8090")
ADMIN = os.environ.get("IAG_ADMIN", "admin")
PASSWORD = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")


DB = os.environ.get("IAG_DB_CONTAINER", "iag-db")


def psql(sql: str) -> str:
    import subprocess

    r = subprocess.run(
        ["docker", "exec", DB, "psql", "-U", "iag_migrate", "-d", "iag", "-tAc", sql],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr}")
    return r.stdout


def log(msg: str) -> None:
    print(f"[live-remediation] {msg}", flush=True)


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30)
    r = client.post("/api/auth/login", json={"username": ADMIN, "password": PASSWORD})
    if r.status_code != 200:
        log(f"login failed {r.status_code}: {r.text[:200]}")
        return 1
    log(f"login ok as {ADMIN}")

    # webhook sink on host; container reaches it via host.docker.internal
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):
            pass

    server = HTTPServer(("0.0.0.0", 8642), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log("webhook sink listening on :8642")

    # 1. rules
    rules_before = client.get("/api/remediation/rules").json()["items"]
    for old in rules_before:
        client.delete(f"/api/remediation/rules/{old['id']}")
    r = client.post("/api/remediation/rules", json={
        "name": "live-email-rule",
        "action": "notify_owner",
        "is_active": True,
        "require_approval": False,
    })
    if r.status_code != 200:
        log(f"rule create failed: {r.text[:200]}")
        return 1
    email_rule_id = r.json()["id"]
    hook_host = os.environ.get("IAG_HOOK_HOST", "host.docker.internal")
    r = client.post("/api/remediation/rules", json={
        "name": "live-webhook-rule",
        "action": "webhook",
        "webhook_url": f"http://{hook_host}:8642/hook",
        "privilege_level": "very_high",
        "is_active": True,
        "require_approval": True,
    })
    webhook_rule_id = r.json()["id"]
    log(f"rules created: email={email_rule_id} webhook={webhook_rule_id}")

    # 2. fresh source owned by ADMIN's identity (admin has a login so
    #    source_owner review mode resolves admin as reviewer; D7
    #    recipient = owner identity email)
    r = client.post("/api/sources", json={
        "name": "live-remediation-src",
        "source_type": "sql",
        "owner_employee_id": "E-ADMIN",  # API contract: employee_id, not identity id
    })
    if r.status_code not in (200, 201, 409):
        log(f"source create failed: {r.text[:200]}")
        return 1
    srcs = client.get("/api/sources").json()["items"]
    src = next(s for s in srcs if s["name"] == "live-remediation-src")
    source_id = src["id"]
    log(f"source {source_id} (owner admin identity 1)")

    # 3. plant a demo access table; sync pulls it (email rule: low
    #    privilege to dodge approval gate; webhook rule: pattern ^Live.*)
    log("planting demo access table")
    psql("DROP TABLE IF EXISTS live_remediation_demo")
    psql(
        "CREATE TABLE live_remediation_demo (account TEXT, entitlement TEXT, privilege TEXT); "
        "INSERT INTO live_remediation_demo VALUES "
        "('liveuser1', 'LiveAdmin', 'high'), "
        "('liveuser2', 'ReadOnly', 'low'), "
        "('liveuser3', 'LiveAuditor', 'very_high');"
    )
    app_db_pw = os.environ.get("IAG_APP_DB_PASSWORD", "")
    if not app_db_pw:
        log("need IAG_APP_DB_PASSWORD in env")
        return 1
    r = client.put(f"/api/sources/{source_id}/connector", json={
        "config": {"url": "postgresql+psycopg2://iag_app:$SECRET@iag-db:5432/iag",
                   "query": "SELECT account, entitlement, privilege FROM live_remediation_demo"},
        "secret": app_db_pw,
    })
    if r.status_code != 200:
        log(f"connector PUT failed: {r.text[:300]}")
        return 1
    r = client.post(f"/api/sources/{source_id}/sync", json={"secret": app_db_pw})
    if r.status_code not in (200, 202):
        log(f"sync failed: {r.text[:300]}")
        return 1
    # wait for sync completion (sync worker polls every 30s)
    for _ in range(45):
        time.sleep(2)
        runs = client.get(f"/api/sources/{source_id}/syncs").json()["items"]
        if runs and runs[0]["status"] == "done":
            break
    else:
        log(f"sync did not complete; last={runs[0] if runs else None}")
        return 1
    log("sync completed")

    accounts = client.get(f"/api/sources/{source_id}/accounts").json()["items"]
    log(f"accounts: {[(a['id'], a['account_value'], a['privilege_level']) for a in accounts]}")

    # house style (see live_enforce_check): connector sync leaves
    # Account.entitlement_id NULL by design and no API sets it; bind from
    # the demo table so campaign reviews have access rows to cover.
    psql(
        f"UPDATE accounts a SET entitlement_id = e.id "
        f"FROM live_remediation_demo d, entitlements e "
        f"WHERE a.account_value = d.account AND e.name = d.entitlement "
        f"AND a.data_source_id = {source_id} AND e.data_source_id = {source_id}"
    )

    # sync also leaves Account.identity_id NULL; create demo identities and
    # bind (same house style) - campaign review generation skips accounts
    # with no owning identity (start_campaign: `if a.identity_id is None`).
    for i, uname in enumerate(("liveuser1", "liveuser2", "liveuser3"), start=1):
        r = client.post("/api/identities", json={
            "employee_id": f"LR-{uname}",
            "username": uname,
            "email": f"{uname}@iag.local",
            "first_name": "Live",
            "last_name": f"Proof{i}",
        })
        if r.status_code not in (200, 201, 409):
            log(f"identity create {uname} failed: {r.text[:200]}")
            return 1
    psql(
        f"UPDATE accounts a SET identity_id = i.id FROM identities i "
        f"WHERE a.account_value = i.username AND a.data_source_id = {source_id}"
    )

    # 4. campaign over this source
    r = client.post("/api/campaigns", json={
        "name": "live-remediation-campaign",
        "scope": {"data_source_ids": [source_id]},
    })
    if r.status_code not in (200, 201, 409):
        log(f"campaign create failed: {r.text[:200]}")
        return 1
    camps = client.get("/api/campaigns").json()["items"]
    camp = next(c for c in camps if c["name"].startswith("live-remediation-"))
    campaign_id = camp["id"]
    # stage then start (409 lesson from Phase B)
    r = client.post(f"/api/campaigns/{campaign_id}/stage")
    if r.status_code not in (200, 409):
        log(f"stage failed: {r.text[:200]}")
        return 1
    r = client.post(f"/api/campaigns/{campaign_id}/start")
    if r.status_code not in (200, 409):
        log(f"start failed: {r.text[:200]}")
        return 1
    log(f"campaign {campaign_id} started")

    # reviews land in the reviewer's queue (source_owner mode -> admin)
    reviews = []
    for _ in range(10):
        reviews = client.get("/api/reviews/queue").json()["items"]
        if reviews:
            break
        time.sleep(1)
    if not reviews:
        log("no reviews created")
        return 1
    log(f"{len(reviews)} reviews queued")

    # 5. revoke every review -> email actions (low priv) + webhook
    #    (pattern ^Live.* and require_approval)
    for rv in reviews:
        r = client.post(f"/api/reviews/{rv['id']}/submit",
                        json={"decision": "revoke", "comments": "live proof"})
        if r.status_code != 200:
            log(f"revoke review {rv['id']} failed: {r.text[:200]}")
            return 1
    log("all reviews revoked")

    # 6. wait for worker: email actions complete (low) or sit in
    #    pending_approval (high/very_high via the global approval gate);
    #    webhook actions sit pending until approved
    actions = []
    for _ in range(30):
        time.sleep(2)
        actions = client.get("/api/remediation/actions?limit=100").json()["items"]
        email_actions_now = [a for a in actions if a["rule_name"] == "live-email-rule"]
        email_low = [a for a in email_actions_now if a["snapshot"].get("privilege_level") == "low"]
        if email_low and all(a["status"] == "completed" for a in email_low):
            break
    for a in actions:
        log(f"action {a['id']} rule={a['rule_name']} priv={a['snapshot'].get('privilege_level')} "
            f"status={a['status']} result={(a['result'] or '')[:60]}")

    email_actions = [a for a in actions if a["rule_name"] == "live-email-rule"]
    hook_actions = [a for a in actions if a["rule_name"] == "live-webhook-rule"]
    email_low = [a for a in email_actions if a["snapshot"].get("privilege_level") == "low"]
    if not email_low or any(a["status"] != "completed" for a in email_low):
        log("FAIL: low-privilege email actions not all completed")
        return 1
    log(f"email leg PASS ({len(email_low)} low-priv delivered without approval)")

    # 7. approve the webhook actions, wait for delivery
    for a in hook_actions:
        if a["status"] == "pending_approval":
            client.put(f"/api/remediation/actions/{a['id']}", json={"op": "approve"})
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        hook_actions = [a for a in client.get("/api/remediation/actions?limit=100").json()["items"]
                        if a["rule_name"] == "live-webhook-rule"]
        if all(a["status"] == "completed" for a in hook_actions):
            break
    if not hook_actions or any(a["status"] != "completed" for a in hook_actions):
        log(f"FAIL: webhook actions stuck: {[(a['id'], a['status'], a['result']) for a in hook_actions]}")
        return 1
    if not received:
        log("FAIL: webhook sink received nothing")
        return 1
    payload = received[0]
    log(f"webhook leg PASS: sink got action_id={payload.get('action_id')} "
        f"entitlement={payload.get('entitlement_name')}")

    # 8. audit chain still valid
    r = client.get("/api/audit/verify")
    if r.status_code != 200 or not r.json().get("valid"):
        log(f"FAIL: audit chain invalid: {r.text[:200]}")
        return 1
    log("audit chain valid")

    # 9. smtp sink got the notify emails (scripts/smtp_sink.py jsonl log)
    sink_log = os.environ.get("SINK_LOG", "scripts/smtp_sink_log.jsonl")
    try:
        with open(sink_log, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
    except FileNotFoundError:
        log(f"FAIL: sink log {sink_log} not found")
        return 1
    rem = [m for m in lines if "Access revoked" in m.get("data", "")]
    if not rem:
        log(f"FAIL: no remediation emails in sink ({len(lines)} messages total)")
        return 1
    log(f"smtp sink holds {len(rem)} remediation email(s), rcpt={rem[0]['to']}")

    server.shutdown()
    log("LIVE REMEDIATION CHECK PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
