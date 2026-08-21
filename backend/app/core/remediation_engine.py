"""Remediation engine: pure rule matching for a revoked review's account.

Pure function of (rules, account-context) -> matched rule ids. Never
writes, never raises on bad regex (an invalid stored pattern makes the
rule non-matching rather than failing the review submit — save-time
validation is the guard, this is defense in depth). sod_engine shape.
"""
from __future__ import annotations

import re

from app.models.remediation import RemediationRule


class AccountContext:
    """The account-side facts a rule matches against, pre-resolved."""

    def __init__(
        self,
        data_source_id: int | None,
        privilege_level: str | None,
        entitlement_name: str | None,
    ):
        self.data_source_id = data_source_id
        self.privilege_level = privilege_level
        self.entitlement_name = entitlement_name or ""


def rule_matches(rule: RemediationRule, ctx: AccountContext) -> bool:
    """All specified conditions must hold (AND); null filters = any."""
    if not rule.is_active:
        return False
    if rule.data_source_id is not None and rule.data_source_id != ctx.data_source_id:
        return False
    if rule.privilege_level is not None and rule.privilege_level != ctx.privilege_level:
        return False
    if rule.entitlement_pattern:
        try:
            if not re.search(rule.entitlement_pattern, ctx.entitlement_name, re.IGNORECASE):
                return False
        except re.error:
            return False  # unreachable via API (validated at save); belt-and-braces
    return True


def matching_rules(rules: list[RemediationRule], ctx: AccountContext) -> list[RemediationRule]:
    return [r for r in rules if rule_matches(r, ctx)]
