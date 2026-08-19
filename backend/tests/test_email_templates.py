"""Template-registry unit tests + enqueue-time rendering proof (SQLite)."""
import io

import pytest

from app.core.email_templates import (
    TemplateRenderError,
    available_templates,
    build_review_url,
    render_email,
)

CSV = ("employee_id,username,email,first_name,last_name,department,manager_employee_id\n"
       "E-1,alice,alice@x.io,Alice,Andrews,Engineering,\n"
       "E-2,bob,bob@x.io,Bob,O'Brien,Engineering,E-1\n")
SRC = "account,entitlement,privilege\nalice,Eng Admin,high\nbob,Read Only,low\n"


def test_registry_has_reminder_template():
    assert "review_reminder" in available_templates()


def test_render_happy_path():
    subject, body = render_email(
        "review_reminder", first_name="Alice", campaign_name="Q3",
        review_url="http://x/reviews?campaign=1")
    assert subject == "[IAG] Review reminder: campaign 'Q3'"
    assert "Hello Alice," in body
    assert "http://x/reviews?campaign=1" in body


def test_render_apostrophe_unicode_passthrough():
    subject, body = render_email(
        "review_reminder", first_name="O'Brien", campaign_name="Ünïcode–Ops",
        review_url="http://x/")
    assert "O'Brien" in body  # no HTML escaping on text emails
    assert "Ünïcode–Ops" in subject and "Ünïcode–Ops" in body


def test_unknown_template_is_loud():
    with pytest.raises(TemplateRenderError, match="unknown email template"):
        render_email("does_not_exist", first_name="A")


def test_missing_context_key_is_loud():
    with pytest.raises(TemplateRenderError, match="failed to render"):
        render_email("review_reminder", first_name="A")  # no campaign_name/url


def test_empty_subject_guard(monkeypatch):
    import app.core.email_templates as mod
    monkeypatch.setitem(mod._TEMPLATES, "broken",
                        {"subject": "  {{ x }}  ", "body": "b"})
    with pytest.raises(TemplateRenderError, match="empty subject"):
        render_email("broken", x="")


def test_build_review_url_default_base():
    url = build_review_url(7)
    assert url.endswith("/reviews?campaign=7")
    assert url.startswith("http://")  # default base, not a relative path


def test_enqueue_renders_templates(admin_client):
    import sqlite3
    admin_client.post("/api/identities/import",
                      files={"file": ("p.csv", io.BytesIO(CSV.encode()), "text/csv")})
    r = admin_client.post("/api/sources", json={
        "name": "Dir", "source_type": "csv", "owner_employee_id": "E-ADMIN"})
    sid = r.json()["id"]
    admin_client.post(f"/api/sources/{sid}/upload",
                      files={"file": ("a.csv", io.BytesIO(SRC.encode()), "text/csv")})
    admin_client.post(f"/api/sources/{sid}/accounts/bulk-link",
                      json={"match_on": "username"})
    r = admin_client.post("/api/campaigns", json={
        "name": "TplCheck", "review_mode": "source_owner"})
    cid = r.json()["id"]
    admin_client.post(f"/api/campaigns/{cid}/stage")
    assert admin_client.post(f"/api/campaigns/{cid}/start").status_code == 200
    rows = admin_client.get(f"/api/reminders/outbox?campaign_id={cid}").json()["items"]
    assert len(rows) == 2
    # subject is exposed by the read API; body is fork-A-private -> read from DB
    assert all("campaign 'TplCheck'" in r_["subject"] for r_ in rows)
    con = sqlite3.connect(admin_client.app.state.test_db_path)
    try:
        bodies = [b for (b,) in con.execute(
            "SELECT body FROM email_outbox WHERE campaign_id = ?", (cid,))]
    finally:
        con.close()
    assert len(bodies) == 2
    assert all(f"/reviews?campaign={cid}" in b for b in bodies)
    # source_owner mode: reviewer is the admin (Ada) for both rows
    assert all("Hello Ada," in b for b in bodies)

