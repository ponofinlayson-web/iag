"""SoD manual run: evaluate rule live, persist snapshot + audit, re-read."""
import io

PEOPLE_CSV = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    "E-1,dave,dave@x.io,Dave,Danger,Finance,\n"
    "E-2,erin,erin@x.io,Erin,Everly,Finance,\n"
)
PAY_CSV = "account,entitlement,privilege\ndave,Payments Admin,high\nerin,Payments Approver,moderate\n"
ERP_CSV = "account,entitlement,privilege\ndave,ERP Deploy,very_high\nerin,ERP Read,low\n"


def _seed(admin_client):
    r = admin_client.post("/api/identities/import",
                          files={"file": ("people.csv", io.BytesIO(PEOPLE_CSV.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    for name, csv_text in (("Payroll", PAY_CSV), ("ERP", ERP_CSV)):
        r = admin_client.post("/api/sources", json={
            "name": name, "source_type": "csv", "owner_employee_id": "E-ADMIN"})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        r = admin_client.post(f"/api/sources/{sid}/upload",
                              files={"file": ("a.csv", io.BytesIO(csv_text.encode()), "text/csv")})
        assert r.status_code == 200, r.text
        admin_client.post(f"/api/sources/{sid}/accounts/bulk-link", json={"match_on": "username"})
    ents = {e["name"]: e["id"] for e in admin_client.get("/api/entitlements").json()["items"]}
    return ents


def _mk_rule(admin_client, ents, **over):
    body = {
        "name": over.pop("name", "Pay vs Deploy"),
        "entitlement_a_id": ents["Payments Admin"],
        "entitlement_b_id": ents["ERP Deploy"],
        "severity": "high",
    }
    body.update(over)
    r = admin_client.post("/api/sod/rules", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_manual_run_finds_dave(admin_client):
    ents = _seed(admin_client)
    rule_id = _mk_rule(admin_client, ents)
    r = admin_client.post(f"/api/sod/rules/{rule_id}/run")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["violation_count"] == 1
    v = body["violations"][0]
    assert v["employee_id"] == "E-1"
    assert v["identity_name"] == "Dave Danger"
    assert {v["entitlement_a"], v["entitlement_b"]} == {"Payments Admin", "ERP Deploy"}
    assert v["severity"] == "high"
    # audit entry landed, chain still valid
    entries = admin_client.get("/api/audit", params={"action": "sod_rule_run"}).json()["items"]
    assert len(entries) == 1
    assert entries[0]["entity_id"] == rule_id
    assert admin_client.get("/api/audit/verify").json()["valid"] is True
    # stored evidence re-reads by run_id with identical content
    r = admin_client.get(f"/api/sod/runs/{body['run_id']}")
    assert r.status_code == 200, r.text
    stored = r.json()
    assert stored["violation_count"] == 1
    assert stored["violations"][0]["employee_id"] == "E-1"
    # rules list carries last_run for the UI
    items = admin_client.get("/api/sod/rules").json()["items"]
    mine = [i for i in items if i["id"] == rule_id][0]
    assert mine["last_run"]["run_id"] == body["run_id"]
    assert mine["last_run"]["violation_count"] == 1


def test_manual_run_evidence_survives_rule_edit(admin_client):
    ents = _seed(admin_client)
    rule_id = _mk_rule(admin_client, ents)
    run_id = admin_client.post(f"/api/sod/rules/{rule_id}/run").json()["run_id"]
    # rename the rule after the run: stored snapshot must not change
    r = admin_client.put(f"/api/sod/rules/{rule_id}", json={
        "name": "Renamed", "entitlement_a_id": ents["Payments Admin"],
        "entitlement_b_id": ents["ERP Deploy"], "severity": "very_high"})
    assert r.status_code == 200
    stored = admin_client.get(f"/api/sod/runs/{run_id}").json()
    assert stored["violations"][0]["rule_name"] == "Pay vs Deploy"
    assert stored["violations"][0]["severity"] == "high"


def test_manual_run_inactive_rule_still_evaluates(admin_client):
    ents = _seed(admin_client)
    rule_id = _mk_rule(admin_client, ents, is_active=False)
    r = admin_client.post(f"/api/sod/rules/{rule_id}/run")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["violation_count"] == 1
    # audit records that the rule was inactive at run time
    entry = admin_client.get("/api/audit", params={"action": "sod_rule_run"}).json()["items"][0]
    assert "rule_active\": false" in entry["details"] or "rule_active\":false" in entry["details"]


def test_manual_run_no_violations(admin_client):
    ents = _seed(admin_client)
    rule_id = _mk_rule(admin_client, ents, name="Approver vs Reader",
                       entitlement_b_id=ents["ERP Read"])
    r = admin_client.post(f"/api/sod/rules/{rule_id}/run")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["violation_count"] == 0
    assert body["violations"] == []
    r = admin_client.get(f"/api/sod/runs/{body['run_id']}")
    assert r.status_code == 200
    assert r.json()["violations"] == []


def test_manual_run_404(admin_client):
    ents = _seed(admin_client)
    assert admin_client.post("/api/sod/rules/99999/run").status_code == 404


def test_manual_run_requires_auth(client):
    # client fixture here has no login: neither write nor read reach the handler
    assert client.get("/api/sod/runs/nonexistent").status_code == 401
    assert client.post("/api/sod/rules/1/run").status_code == 401
