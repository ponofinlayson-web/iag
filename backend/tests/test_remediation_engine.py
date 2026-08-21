"""Remediation engine: pure rule matching (Phase A) + trigger wiring (B)."""
from __future__ import annotations

import json

import pytest

from app.core.remediation_engine import AccountContext, matching_rules, rule_matches
from app.models.remediation import (
    DEFAULT_CONFIG,
    RemediationAction,
    RemediationRule,
    RemediationSettings,
    RemediationStatus,
)


def _rule(**kw) -> RemediationRule:
    defaults = dict(name="r", action="notify_owner", is_active=True)
    defaults.update(kw)
    return RemediationRule(**defaults)


def _ctx(source=1, privilege="high", ent="domain-admins"):
    return AccountContext(source, privilege, ent)


class TestRuleMatching:
    def test_catch_all_matches_everything(self):
        rules = [_rule(name="catch-all")]
        assert matching_rules(rules, _ctx(source=9, privilege=None, ent="zzz")) == [rules[0]]

    def test_source_filter_match_and_miss(self):
        r = _rule(name="src", data_source_id=1)
        assert matching_rules([r], _ctx(source=1)) == [r]
        assert matching_rules([r], _ctx(source=2)) == []

    def test_privilege_filter_match_and_miss(self):
        r = _rule(name="priv", privilege_level="high")
        assert matching_rules([r], _ctx(privilege="high")) == [r]
        assert matching_rules([r], _ctx(privilege="low")) == []

    def test_regex_match_and_miss_case_insensitive(self):
        r = _rule(name="pat", entitlement_pattern=r"^adm")
        assert matching_rules([r], _ctx(ent="ADMIN-UI")) == [r]
        assert matching_rules([r], _ctx(ent="user-portal")) == []

    def test_and_semantics_all_conditions(self):
        r = _rule(name="and", data_source_id=1, privilege_level="very_high",
                  entitlement_pattern=r"root")
        assert matching_rules([r], _ctx(source=1, privilege="very_high", ent="root-access")) == [r]
        assert matching_rules([r], _ctx(source=1, privilege="very_high", ent="user")) == []
        assert matching_rules([r], _ctx(source=2, privilege="very_high", ent="root-access")) == []

    def test_inactive_rule_never_matches(self):
        r = _rule(name="off", is_active=False)
        assert matching_rules([r], _ctx()) == []

    def test_invalid_regex_does_not_raise_rule_skipped(self):
        r = _rule(name="bad", entitlement_pattern=r"[unclosed")
        assert matching_rules([r], _ctx()) == []
        assert rule_matches(r, _ctx()) is False


class TestDefaults:
    def test_default_config_shape(self):
        assert DEFAULT_CONFIG["enabled"] is True
        assert DEFAULT_CONFIG["default_action"] == "notify_owner"
        assert DEFAULT_CONFIG["require_approval_for_high_risk"] is True


class TestSnapshotRoundTrip:
    def test_action_snapshot_dict_round_trip(self):
        a = RemediationAction(
            review_id=1, action_type="notify_owner",
            snapshot=json.dumps({"identity_name": "Ada", "privilege": "high"}),
        )
        assert a.snapshot_dict()["identity_name"] == "Ada"

    def test_settings_config_round_trip(self):
        s = RemediationSettings(id=1, config=json.dumps(DEFAULT_CONFIG))
        assert s.config_dict()["enabled"] is True


class TestStatusVocabulary:
    def test_status_values(self):
        assert RemediationStatus.PENDING_APPROVAL == "pending_approval"
        assert RemediationStatus.APPROVED == "approved"
        assert RemediationStatus.EXECUTING == "executing"
        assert RemediationStatus.COMPLETED == "completed"
        assert RemediationStatus.FAILED == "failed"
        assert RemediationStatus.CANCELLED == "cancelled"
