"""feature 6 phase A: scim_settings table + remediation_rules.target column
Revision ID: 0008
Revises: 0007
Create Date: 2026-08-22
"""
import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.models.scim import DEFAULT_SCIM_CONFIG

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 pins its table list, so fresh volumes do NOT pre-create
    # scim_settings; this revision owns it (0002-0007 pattern). Surface
    # defaults OFF: enabled=false + no token (spec: two deliberate acts).
    op.create_table(
        "scim_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("token_prefix", sa.String(length=16), nullable=True),
        sa.Column("token_created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # Raw INSERT bypasses ORM defaults, so updated_at is bound explicitly
    # (naive-UTC, app.models.identity.utcnow convention; sa.text carries no
    # datetime comparison logic that could reject it).
    op.execute(
        sa.text(
            "INSERT INTO scim_settings (id, config, updated_at) VALUES (1, :cfg, :ts)"
        ).bindparams(
            cfg=json.dumps(DEFAULT_SCIM_CONFIG),
            ts=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    # remediation_rules.target is GUARDED (0004 pattern): SQLite test DBs
    # build from CURRENT metadata via create_all, so the column already
    # exists there; live Postgres volumes get it added here.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("remediation_rules")}
    if "target" not in existing:
        op.add_column(
            "remediation_rules",
            sa.Column("target", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("remediation_rules")}
    if "target" in existing:
        op.drop_column("remediation_rules", "target")
    op.drop_table("scim_settings")
