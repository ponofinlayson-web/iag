"""feature 3: remediation rules, actions, settings
Revision ID: 0005
Revises: 0004
Create Date: 2026-08-20
"""
import json

import sqlalchemy as sa
from alembic import op

from app.models.remediation import DEFAULT_CONFIG

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 pins its table list, so fresh volumes do NOT pre-create these
    # tables; each revision owns its own (no add_column-style guard
    # needed here, unlike 0004). Seed the single settings row (D4) with
    # defaults so first boot has deterministic config.
    op.create_table(
        "remediation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data_source_id", sa.Integer(),
                  sa.ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("privilege_level", sa.String(length=20), nullable=True),
        sa.Column("entitlement_pattern", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False,
                  server_default="notify_owner"),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("require_approval", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("times_triggered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_executed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_remediation_rules_data_source_id", "remediation_rules", ["data_source_id"]
    )
    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(),
                  sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(),
                  sa.ForeignKey("remediation_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_id", sa.Integer(),
                  sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="approved"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("approved_by_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_remediation_actions_review_id", "remediation_actions", ["review_id"])
    op.create_index("ix_remediation_actions_status", "remediation_actions", ["status"])
    op.create_table(
        "remediation_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config", sa.Text(), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO remediation_settings (id, config) VALUES (1, :cfg)"
        ).bindparams(cfg=json.dumps(DEFAULT_CONFIG))
    )


def downgrade() -> None:
    op.drop_table("remediation_settings")
    op.drop_index("ix_remediation_actions_status", table_name="remediation_actions")
    op.drop_index("ix_remediation_actions_review_id", table_name="remediation_actions")
    op.drop_table("remediation_actions")
    op.drop_index(
        "ix_remediation_rules_data_source_id", table_name="remediation_rules"
    )
    op.drop_table("remediation_rules")
