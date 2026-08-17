"""End-to-end governance workflow: identities -> sources -> campaign -> reviews -> audit."""
import io
CSV_ROWS = "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
CSV_ROWS += "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
CSV_ROWS += "E-2,bob,bob@x.io,Bob,Brown,Engineering,E-1\n"
CSV_ROWS += "E-3,carol,carol@x.io,Carol,Chen,Finance,\n"
SRC_CSV = "account,entitlement,privilege\nalice,Engineering Admin,high\nbob,Read Only,low\ncarol,Finance Approver,moderate\nsvc-jira,Jira Admin,very_high\n"
def test_full_workflow(admin_client):
    # 1. Import identities
    r = admin_client.post("/api/identities/import",
                          files={"file": ("people.csv", io.BytesIO(CSV_ROWS.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3
    # 2. Create source owned by the admin identity (E-ADMIN) so the
    #    source_owner reviewer resolves to the admin's login account.
    r = admin_client.post("/api/sources", json={
        "name": "App Directory", "source_type": "csv", "owner_employee_id": "E-ADMIN",
    })
    assert r.status_code == 200, r.text
    src_id = r.json()["id"]
    # 3. Upload access snapshot
    r = admin_client.post(f"/api/sources/{src_id}/upload",
                          files={"file": ("access.csv", io.BytesIO(SRC_CSV.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accounts_created"] == 4
    assert body["entitlements_created"] == 4
    # 4. Bulk link by username
    r = admin_client.post(f"/api/sources/{src_id}/accounts/bulk-link", json={"match_on": "username"})
    assert r.status_code == 200, r.text
    assert r.json()["linked"] == 3  # svc-jira stays unlinked
    # 5. Campaign: create, preview, stage, start
    r = admin_client.post("/api/campaigns", json={"name": "Q1 Access Review", "review_mode": "source_owner"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = admin_client.post(f"/api/campaigns/{cid}/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["total_in_scope"] == 4
    assert preview["will_create"] == 4  # owner (admin) has a login
    assert preview["skipped"] == []
    r = admin_client.post(f"/api/campaigns/{cid}/stage")
    assert r.status_code == 200
    r = admin_client.post(f"/api/campaigns/{cid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["reviews_created"] == 4
    # 6. Reviews: alice reviews all 4 (she is source owner)
    r = admin_client.get("/api/reviews/queue")
    assert r.status_code == 200
    queue = r.json()
    assert queue["total"] == 4
    review_ids = [it["id"] for it in queue["items"]]
    # revoke without comment must fail
    r = admin_client.post(f"/api/reviews/{review_ids[0]}/submit", json={"decision": "revoke"})
    assert r.status_code == 400
    r = admin_client.post(f"/api/reviews/{review_ids[0]}/submit",
                          json={"decision": "revoke", "comments": "svc account unused"})
    assert r.status_code == 200
    r = admin_client.post("/api/reviews/bulk-submit", json={
        "review_ids": review_ids[1:], "decision": "approve",
    })
    assert r.status_code == 200
    assert r.json()["submitted"] == 3
    # 7. Campaign auto-completes
    r = admin_client.get(f"/api/campaigns/{cid}")
    assert r.json()["status"] == "completed"
    # 8. Audit chain verifies
    r = admin_client.get("/api/audit/verify")
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert r.json()["entries"] >= 10
