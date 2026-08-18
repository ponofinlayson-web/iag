"""sod rules table
Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08
"""
import sqlalchemy as sa
from alembic import op
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table(
        "sod_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entitlement_a_id", sa.Integer(),
                  sa.ForeignKey("entitlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_b_id", sa.Integer(),
                  sa.ForeignKey("entitlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="high"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sod_rules_entitlement_a_id", "sod_rules", ["entitlement_a_id"])
    op.create_index("ix_sod_rules_entitlement_b_id", "sod_rules", ["entitlement_b_id"])
def downgrade() -> None:
    op.drop_index("ix_sod_rules_entitlement_b_id", table_name="sod_rules")
    op.drop_index("ix_sod_rules_entitlement_a_id", table_name="sod_rules")
    op.drop_table("sod_rules")
