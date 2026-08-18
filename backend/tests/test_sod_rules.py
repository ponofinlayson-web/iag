"""SoD rule CRUD: validation, audit discipline on every write."""
import io
SRC_CSV = "account,entitlement,privilege\nalice,Payments Admin,high\nbob,Payments Approver,moderate\n"
def _setup_source(admin_client):
    r = admin_client.post("/api/sources", json={
        "name": "Payroll", "source_type": "csv", "owner_employee_id": "E-ADMIN"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = admin_client.post(f"/api/sources/{sid}/upload",
                          files={"file": ("access.csv", io.BytesIO(SRC_CSV.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    ents = admin_client.get("/api/entitlements").json()["items"]
    return sid, {e["name"]: e["id"] for e in ents}
def test_rule_crud_and_audit(admin_client):
    _, ents = _setup_source(admin_client)
    a, b = ents["Payments Admin"], ents["Payments Approver"]
    # create
    r = admin_client.post("/api/sod/rules", json={
        "name": "Paymaker vs Paychecker", "entitlement_a_id": a, "entitlement_b_id": b})
    assert r.status_code == 200, r.text
    rule_id = r.json()["id"]
    # duplicate name
    r = admin_client.post("/api/sod/rules", json={
        "name": "Paymaker vs Paychecker", "entitlement_a_id": a, "entitlement_b_id": b})
    assert r.status_code == 409
    # self-pair and unknown refs rejected
    assert admin_client.post("/api/sod/rules", json={
        "name": "self", "entitlement_a_id": a, "entitlement_b_id": a}).status_code == 400
    assert admin_client.post("/api/sod/rules", json={
        "name": "ghost", "entitlement_a_id": a, "entitlement_b_id": 99999}).status_code == 400
    assert admin_client.post("/api/sod/rules", json={
        "name": "badsev", "entitlement_a_id": a, "entitlement_b_id": b,
        "severity": "extreme"}).status_code == 400
    # update
    r = admin_client.put(f"/api/sod/rules/{rule_id}", json={
        "name": "Paymaker vs Paychecker", "entitlement_a_id": a, "entitlement_b_id": b,
        "severity": "very_high"})
    assert r.status_code == 200
    # list shows names resolved
    items = admin_client.get("/api/sod/rules").json()["items"]
    assert items[0]["severity"] == "very_high"
    assert items[0]["entitlement_a_name"] == "Payments Admin"
    # audit chain intact and rule writes recorded
    entries = admin_client.get("/api/audit", params={"action": "sod_rule_created"}).json()["items"]
    assert len(entries) == 1
    v = admin_client.get("/api/audit/verify").json()
    assert v["valid"] is True
    # delete
    assert admin_client.delete(f"/api/sod/rules/{rule_id}").status_code == 200
    assert admin_client.get(f"/api/sod/rules/{rule_id}").status_code == 404
    v = admin_client.get("/api/audit/verify").json()
    assert v["valid"] is True
def test_rules_require_auth(client):
    # unauthenticated: neither read nor write reach the handler
    assert client.get("/api/sod/rules").status_code == 401
    r = client.post("/api/sod/rules", json={
        "name": "x", "entitlement_a_id": 1, "entitlement_b_id": 2})
    assert r.status_code == 401
