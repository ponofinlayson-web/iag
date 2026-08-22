"""Feature 6 phase A: pure SCIM helpers (mapping, filter, PATCH, SPC)."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.core.scim import (
    PAGE_MAX_COUNT,
    ScimError,
    _FILTER_RE,
    identity_to_scim,
    normalize_patch,
    parse_filter,
    scim_to_identity_fields,
    service_provider_config,
)


class _Identity:
    """Test double with exactly the attributes identity_to_scim reads."""

    def __init__(self, **kwargs):
        defaults = dict(
            employee_id="E-1",
            username=None,
            email=None,
            first_name=None,
            last_name=None,
            department=None,
            job_title=None,
            is_active=True,
            created_at=datetime(2026, 8, 22, 12, 0, 0),
            updated_at=datetime(2026, 8, 22, 12, 30, 0),
        )
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


# --- ServiceProviderConfig ---


def test_spc_is_honest():
    spc = service_provider_config()
    assert spc["patch"]["supported"] is True
    assert spc["bulk"]["supported"] is False
    assert spc["sort"]["supported"] is False
    assert spc["etag"]["supported"] is False
    assert spc["changePassword"]["supported"] is False
    assert spc["filter"] == {"supported": True, "maxResults": PAGE_MAX_COUNT}
    assert spc["schemas"] == ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"]


# --- filter parser ---


@pytest.mark.parametrize(
    "expr,expected",
    [
        ('userName eq "jdoe"', ("userName", "jdoe")),
        ('emails.value eq "a@b.c"', ("emails.value", "a@b.c")),
        ('externalId eq "E-9"', ("externalId", "E-9")),
        ('  username   eq   "x y" ', ("userName", "x y")),  # case + whitespace
    ],
)
def test_parse_filter_accepts_eq_only(expr, expected):
    assert parse_filter(expr) == expected


def test_parse_filter_none_and_blank():
    assert parse_filter(None) is None
    assert parse_filter("   ") is None


@pytest.mark.parametrize(
    "expr",
    [
        'userName co "j"',           # non-EQ operator
        'userName eq "a" and emails.value eq "b"',  # two clauses
        'displayName eq "x"',        # attribute outside the subset
        'userName eq jdoe',          # unquoted value
        'userName eq "jdoe" junk',   # trailing junk (v1 accepted this)
        'emails.value sw "a"',
    ],
)
def test_parse_filter_rejects_everything_else(expr):
    with pytest.raises(ScimError) as err:
        parse_filter(expr)
    assert err.value.status == 400


def test_filter_regex_rejects_trailing_junk():
    # Direct regex check: fullmatch anchoring is the designed-out v1 defect.
    assert _FILTER_RE.fullmatch('userName eq "jdoe" junk') is None


# --- Identity -> SCIM User ---


def test_identity_to_scim_full():
    resource = identity_to_scim(_Identity(
        username="jdoe", email="jdoe@x.c", first_name="Jane", last_name="Doe",
        job_title="Dev", department="Eng",
    ))
    assert resource["schemas"] == ["urn:ietf:params:scim:schemas:core:2.0:User"]
    assert resource["id"] == "E-1"
    assert resource["externalId"] == "E-1"  # D3: employee_id verbatim
    assert resource["userName"] == "jdoe"
    assert resource["active"] is True
    assert resource["name"] == {"givenName": "Jane", "familyName": "Doe"}
    assert resource["displayName"] == "Jane Doe"
    assert resource["emails"] == [{"value": "jdoe@x.c", "type": "work", "primary": True}]
    assert resource["title"] == "Dev"
    assert resource["department"] == "Eng"
    assert resource["meta"]["resourceType"] == "User"
    assert resource["meta"]["created"] == "2026-08-22T12:00:00Z"  # naive-UTC + Z
    assert "phoneNumbers" not in resource  # v1 placeholder designed out


def test_identity_to_scim_fallbacks():
    minimal = identity_to_scim(_Identity())
    assert minimal["userName"] == "user_E-1"  # username -> email -> f"user_{id}"
    assert "name" not in minimal
    assert "displayName" not in minimal
    assert "emails" not in minimal

    email_only = identity_to_scim(_Identity(email="a@b.c"))
    assert email_only["userName"] == "a@b.c"
    assert email_only["emails"][0]["value"] == "a@b.c"

    inactive = identity_to_scim(_Identity(is_active=False))
    assert inactive["active"] is False


def test_identity_to_scim_meta_null_when_no_timestamps():
    resource = identity_to_scim(_Identity(created_at=None, updated_at=None))
    assert resource["meta"]["created"] is None
    assert resource["meta"]["lastModified"] is None


# --- SCIM User payload -> Identity fields ---


def test_scim_to_identity_fields_full():
    fields = scim_to_identity_fields({
        "userName": "jdoe",
        "emails": [
            {"value": "personal@x.c"},
            {"value": "work@x.c", "primary": True},
        ],
        "name": {"givenName": "Jane", "familyName": "Doe"},
        "title": "Dev",
        "department": "Eng",
        "active": True,
    })
    assert fields == {
        "username": "jdoe",
        "email": "work@x.c",  # primary wins over first
        "first_name": "Jane",
        "last_name": "Doe",
        "job_title": "Dev",
        "department": "Eng",
        "is_active": True,
    }


def test_scim_to_identity_fields_email_fallback_first():
    fields = scim_to_identity_fields({
        "emails": [{"value": "a@x.c"}, {"value": "b@x.c", "primary": False}],
    })
    assert fields["email"] == "a@x.c"  # no primary -> first with a value


def test_scim_to_identity_fields_display_name_parsed_only_without_name():
    fields = scim_to_identity_fields({"displayName": "Jane van Doe"})
    assert fields["first_name"] == "Jane"
    assert fields["last_name"] == "van Doe"  # everything after the first space

    with_name = scim_to_identity_fields({
        "displayName": "IGNORED", "name": {"givenName": "Jane"},
    })
    assert with_name["first_name"] == "Jane"
    assert "last_name" not in with_name

    single = scim_to_identity_fields({"displayName": "Cher"})
    assert single["first_name"] == "Cher"
    assert "last_name" not in single


def test_scim_to_identity_fields_manager_phone_ignored():
    fields = scim_to_identity_fields({
        "userName": "jdoe",
        "manager": {"value": "E-2"},
        "phoneNumbers": [{"value": "555", "type": "work"}],
    })
    assert fields == {"username": "jdoe"}


def test_scim_to_identity_fields_empty_absent_values_skipped():
    fields = scim_to_identity_fields({
        "userName": "", "title": None, "department": "", "active": None,
    })
    assert fields == {}


# --- PATCH normalization ---


def test_normalize_patch_okta_deprovision_shape():
    # The path-less form Okta actually sends; feeds the In-mapping directly.
    merged = normalize_patch({"Operations": [{"op": "replace", "value": {"active": False}}]})
    assert merged == {"active": False}
    assert scim_to_identity_fields(merged) == {"is_active": False}


def test_normalize_patch_path_form_case_insensitive():
    merged = normalize_patch({
        "Operations": [{"op": "Replace", "path": "Name.familyName", "value": "Smith"}]
    })
    assert merged == {"name.familyName": "Smith"}


def test_normalize_patch_multiple_ops_merge():
    merged = normalize_patch({"Operations": [
        {"op": "replace", "path": "active", "value": False},
        {"op": "replace", "path": "title", "value": "Gone"},
    ]})
    assert merged == {"active": False, "title": "Gone"}


def test_normalize_patch_writable_paths_round_trip():
    merged = normalize_patch({"Operations": [
        {"op": "replace", "path": "userName", "value": "new"},
        {"op": "replace", "path": "name.givenName", "value": "A"},
        {"op": "replace", "path": "name.familyName", "value": "B"},
        {"op": "replace", "path": "displayName", "value": "A B"},
        {"op": "replace", "path": "department", "value": "D"},
        {"op": "replace", "path": "emails", "value": [{"value": "n@x.c"}]},
    ]})
    fields = scim_to_identity_fields(merged)
    assert fields["username"] == "new"
    assert fields["first_name"] == "A"
    assert fields["last_name"] == "B"
    assert fields["email"] == "n@x.c"
    assert fields["department"] == "D"
    # displayName does NOT parse when name parts are present (both set above)
    assert "displayName" not in merged or merged["displayName"] == "A B"


@pytest.mark.parametrize(
    "payload,detail_part",
    [
        ({"Operations": [{"op": "add", "path": "active", "value": True}]}, "replace only"),
        ({"Operations": [{"op": "remove", "path": "name"}]}, "replace only"),
        ({"Operations": [{"op": "replace", "path": "meta.created", "value": "x"}]}, "Unsupported path"),
        ({"Operations": [{"op": "replace", "path": "name.middle", "value": "X"}]}, "Unsupported path"),
        ({"Operations": []}, "non-empty"),
        ({"Operations": "nope"}, "non-empty"),
        ({"Operations": [{"op": "replace", "value": "scalar"}]}, "object value"),
        ({"Operations": ["nope"]}, "must be an object"),
        ({"Operations": [{"op": "replace", "value": {"nickname": "x"}}]}, "Unsupported path"),
    ],
)
def test_normalize_patch_rejects_out_of_subset(payload, detail_part):
    with pytest.raises(ScimError) as err:
        normalize_patch(payload)
    assert err.value.status == 400
    assert detail_part in err.value.detail


# --- ScimError envelope ---


def test_scim_error_envelope_shape():
    envelope = ScimError(404, "User not found").envelope()
    assert envelope == {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": "404",
        "detail": "User not found",
    }


# --- model round-trip (SQLite, create_all builds CURRENT metadata) ---


async def test_scim_settings_and_rule_target_round_trip():
    import json

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.db import Base, build_engine
    from app.models import RemediationRule, ScimSettings
    from app.models.remediation import ENFORCE_TARGETS

    engine = build_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        row = ScimSettings(
            id=1,
            config=json.dumps({"enabled": False}),
            token_hash="a" * 64,
            token_prefix="iag_scim_abc",
        )
        db.add(row)
        rule = RemediationRule(
            name="r1", action="enforce", target="disable_account",
            require_approval=True,
        )
        db.add(rule)
        await db.flush()

        fetched = await db.get(ScimSettings, 1)
        assert fetched.config_dict() == {"enabled": False}
        assert fetched.token_hash == "a" * 64
        assert fetched.token_prefix == "iag_scim_abc"
        assert fetched.token_created_at is None

        rule_row = (await db.execute(select(RemediationRule))).scalar_one()
        assert rule_row.action == "enforce"
        assert rule_row.target == "disable_account"
        assert rule_row.target in ENFORCE_TARGETS

        # null target = remove_entitlement default (D6)
        db.add(RemediationRule(name="r2", action="enforce"))
        await db.flush()
        rules = (await db.execute(select(RemediationRule).order_by(RemediationRule.id))).scalars().all()
        assert rules[1].target is None
    await engine.dispose()




