"""SoD E2E: import violating access -> rule -> preview flags, review shows, submit manual."""
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
    ids = {i["employee_id"]: i["id"] for i in admin_client.get("/api/identities").json()["items"]}
    ents = {}
    for name, csv_text in (("Payroll", PAY_CSV), ("ERP", ERP_CSV)):
        r = admin_client.post("/api/sources", json={
            "name": name, "source_type": "csv", "owner_employee_id": "E-ADMIN"})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        r = admin_client.post(f"/api/sources/{sid}/upload",
                              files={"file": ("a.csv", io.BytesIO(csv_text.encode()), "text/csv")})
        assert r.status_code == 200, r.text
        admin_client.post(f"/api/sources/{sid}/accounts/bulk-link", json={"match_on": "username"})
    for e in admin_client.get("/api/entitlements").json()["items"]:
        ents[e["name"]] = e["id"]
    return ids, ents
def test_sod_e2e_preview_and_review(admin_client):
    ids, ents = _seed(admin_client)
    r = admin_client.post("/api/sod/rules", json={
        "name": "Pay vs Deploy",
        "entitlement_a_id": ents["Payments Admin"],
        "entitlement_b_id": ents["ERP Deploy"],
        "severity": "high",
    })
    assert r.status_code == 200, r.text
    # campaign over all accounts
    r = admin_client.post("/api/campaigns", json={"name": "SoD Check", "review_mode": "source_owner"})
    cid = r.json()["id"]
    r = admin_client.post(f"/api/campaigns/{cid}/preview")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["sod"]["identities_flagged"] == 1  # dave only
    flagged = [i for i in p["sample"] if i.get("sod_violations")]
    assert len(flagged) == 2  # both of dave's accounts
    v = flagged[0]["sod_violations"][0]
    assert v["rule_name"] == "Pay vs Deploy"
    assert v["severity"] == "high"
    assert {v["entitlement_a"], v["entitlement_b"]} == {"Payments Admin", "ERP Deploy"}
    # start + review detail shows violations; submit remains manual
    assert admin_client.post(f"/api/campaigns/{cid}/stage").status_code == 200
    assert admin_client.post(f"/api/campaigns/{cid}/start").status_code == 200
    queue = admin_client.get("/api/reviews/queue").json()["items"]
    dave_reviews = []
    for it in queue:
        det = admin_client.get(f"/api/reviews/{it['id']}").json()
        if det["sod_violations"]:
            dave_reviews.append(det)
    assert len(dave_reviews) == 2
    assert dave_reviews[0]["sod_violations"][0]["rule_name"] == "Pay vs Deploy"
    # manual approval still allowed — engine informs, never decides
    for it in queue:
        r = admin_client.post(f"/api/reviews/{it['id']}/submit",
                              json={"decision": "approve", "comments": "reviewed"})
        assert r.status_code == 200, r.text
    det = admin_client.get(f"/api/reviews/{dave_reviews[0]['id']}").json()
    assert det["status"] == "approved"
    assert det["sod_violations"]  # still visible after decision
    assert admin_client.get("/api/audit/verify").json()["valid"] is True
def test_inactive_rule_flags_nothing(admin_client):
    ids, ents = _seed(admin_client)
    r = admin_client.post("/api/sod/rules", json={
        "name": "Pay vs Deploy", "entitlement_a_id": ents["Payments Admin"],
        "entitlement_b_id": ents["ERP Deploy"], "is_active": False})
    assert r.status_code == 200, r.text
    r = admin_client.post("/api/campaigns", json={"name": "SoD Off", "review_mode": "source_owner"})
    cid = r.json()["id"]
    p = admin_client.post(f"/api/campaigns/{cid}/preview").json()
    assert p["sod"]["identities_flagged"] == 0
    assert all(not i.get("sod_violations") for i in p["sample"])
