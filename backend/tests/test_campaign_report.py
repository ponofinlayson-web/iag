"""Phase D: campaign report JSON + streamed report.csv."""
from __future__ import annotations

import csv
import io
import json

from app.models.user import Role
from tests.test_apikeys_auth import _seed_key


def _hdr(key):
    return {"Authorization": f"Bearer {key}"}


PEOPLE_CSV = (
    "employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
    "E-R1,rita,rita@x.io,Rita,Reviewer,HR,\n"
    "E-R2,bob,bob@x.io,Bob,Bottleneck,IT,E-R1\n"
    "E-R3,eva,eva@x.io,Eva,Evaluate,IT,E-R1\n"
)
APP_CSV = (
    "account,entitlement,privilege\n"
    "rita,Payments Approver,moderate\n"
    "bob,ERP Deploy,high\n"
    "eva,ERP Read,low\n"
)


def _fixture(admin_client):
    """Campaign over 3 linked identities, source_owner mode (admin owns the
    source, so admin is the reviewer)."""
    r = admin_client.post(
        "/api/identities/import",
        files={"file": ("p.csv", io.BytesIO(PEOPLE_CSV.encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text
    r = admin_client.post(
        "/api/sources",
        json={"name": "ReportSrc", "source_type": "csv", "owner_employee_id": "E-ADMIN"},
    )
    sid = r.json()["id"]
    r = admin_client.post(
        f"/api/sources/{sid}/upload",
        files={"file": ("a.csv", io.BytesIO(APP_CSV.encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text
    admin_client.post(f"/api/sources/{sid}/accounts/bulk-link", json={"match_on": "username"})
    r = admin_client.post("/api/campaigns", json={"name": "Rep", "review_mode": "source_owner"})
    cid = r.json()["id"]
    admin_client.post(f"/api/campaigns/{cid}/stage")
    admin_client.post(f"/api/campaigns/{cid}/start")
    return cid


def _reviews(admin_client, cid):
    return admin_client.get(f"/api/campaigns/{cid}").json()


def _decide(admin_client, cid, idx, decision, comments=None):
    """Approve/revoke review idx of this campaign (admin is the reviewer)."""
    reviews = admin_client.get("/api/reviews/queue").json()["items"]
    target = [rv for rv in reviews if rv.get("campaign_id") == cid]
    rv = target[idx]
    return admin_client.post(
        f"/api/reviews/{rv['id']}/submit",
        json={"decision": decision, "comments": comments},
    )


def test_report_json_shape(admin_client):
    cid = _fixture(admin_client)
    rep = admin_client.get(f"/api/campaigns/{cid}/report").json()
    assert rep["campaign"]["name"] == "Rep"
    assert rep["campaign"]["status"] in ("active", "completed")
    assert rep["generated_at"]
    comp = rep["completion"]
    assert comp["total"] == 3
    assert comp["completed"] == 0
    assert comp["progress_pct"] == 0.0
    assert rep["decisions"] == {"pending": 3}
    # single reviewer (admin) holds all 3, pending 3
    wl = rep["reviewer_workload"]
    assert len(wl) == 1
    assert wl[0]["assigned"] == 3 and wl[0]["pending"] == 3
    assert rep["revocations"] == []
    assert rep["risk"] is None  # no risk run yet


def test_report_after_decisions_and_risk_run(admin_client):
    cid = _fixture(admin_client)
    r = _decide(admin_client, cid, 0, "revoke", comments="unused entitlement")
    assert r.status_code == 200, r.text
    r = _decide(admin_client, cid, 1, "approve")
    assert r.status_code == 200, r.text
    admin_client.post("/api/risk/runs")
    rep = admin_client.get(f"/api/campaigns/{cid}/report").json()
    assert rep["decisions"] == {"approved": 1, "revoked": 1, "pending": 1}
    comp = rep["completion"]
    assert comp["completed"] == 2 and comp["pending"] == 1
    assert comp["progress_pct"] == round(100 * 2 / 3, 1)
    assert len(rep["revocations"]) == 1
    rev = rep["revocations"][0]
    assert rev["comment"] == "unused entitlement"
    assert rev["entitlement"] and rev["source"] == "ReportSrc"
    assert rev["reviewer"] == "Ada Minnie"  # seeded admin identity display name
    risk = rep["risk"]
    assert risk is not None and risk["run_id"]
    assert risk["scored_in_campaign"] == 3  # rita, bob, eva
    assert sum(risk["band_distribution"].values()) == 3


def test_report_campaign_completed_block(admin_client):
    cid = _fixture(admin_client)
    for _ in range(3):  # queue shrinks per decision; always take the first
        r = _decide(admin_client, cid, 0, "approve")
        assert r.status_code == 200, r.text
    rep = admin_client.get(f"/api/campaigns/{cid}/report").json()
    assert rep["campaign"]["status"] == "completed"
    assert rep["completion"]["progress_pct"] == 100.0
    assert rep["decisions"] == {"approved": 3}


def test_report_csv_shape(admin_client):
    cid = _fixture(admin_client)
    _decide(admin_client, cid, 0, "revoke", comments="unused entitlement")
    text = admin_client.get(f"/api/campaigns/{cid}/report.csv").text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["identity", "employee_id", "source", "entitlement", "account",
                       "privilege", "reviewer", "decision", "decided_at", "comment"]
    assert len(rows) == 4  # header + 3 decisions
    revoked_rows = [r for r in rows[1:] if r[7] == "revoked"]
    assert len(revoked_rows) == 1
    assert revoked_rows[0][9] == "unused entitlement"
    assert revoked_rows[0][2] == "ReportSrc"


def test_report_guards(admin_client, client):
    cid = _fixture(admin_client)
    assert admin_client.get("/api/campaigns/999/report").status_code == 404
    assert admin_client.get("/api/campaigns/999/report.csv").status_code == 404
    rv_key = _seed_key(client, role=Role.REPORT_VIEWER)
    aud_key = _seed_key(client, role=Role.AUDITOR)
    assert client.get(f"/api/campaigns/{cid}/report",
                      headers=_hdr(rv_key)).status_code == 200
    assert client.get(f"/api/campaigns/{cid}/report.csv",
                      headers=_hdr(rv_key)).status_code == 200
    assert client.get(f"/api/campaigns/{cid}/report",
                      headers=_hdr(aud_key)).status_code == 200
    # reviewer session user: 403 (not in ReportViewer roles). Shared cookie
    # jar means admin_client is ALSO rev9 from here on - admin checks above.
    from tests.test_risk_api import _seed_user
    _seed_user(client, "rev9", Role.REVIEWER)
    assert client.get(f"/api/campaigns/{cid}/report").status_code == 403
    assert client.get(f"/api/campaigns/{cid}/report.csv").status_code == 403
    client.cookies.clear()
    assert client.get(f"/api/campaigns/{cid}/report").status_code == 401
