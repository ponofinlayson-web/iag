"""feature 5: risk_snapshots table
Revision ID: 0007
Revises: 0006
Create Date: 2026-08-21
"""
import sqlalchemy as sa
from alembic import op
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None
def upgrade() -> None:
    # 0001 pins its table list, so fresh volumes do NOT pre-create this
    # table; this revision owns it (same pattern as 0002-0006).
    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("identity_id", sa.Integer(),
                  sa.ForeignKey("identities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("identity_employee_id", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("band", sa.String(length=10), nullable=False),
        sa.Column("signals", sa.Text(), nullable=False),
        sa.Column("factors", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_risk_snapshots_run_id", "risk_snapshots", ["run_id"])
    op.create_index("ix_risk_snapshots_identity_computed_at", "risk_snapshots",
                    ["identity_id", "computed_at"])
def downgrade() -> None:
    op.drop_index("ix_risk_snapshots_identity_computed_at", table_name="risk_snapshots")
    op.drop_index("ix_risk_snapshots_run_id", table_name="risk_snapshots")
    op.drop_table("risk_snapshots")
