"""polish pass 2: sod_evaluations table
Revision ID: 0009
Revises: 0008
Create Date: 2026-08-23
"""
import sqlalchemy as sa
from alembic import op
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None
def upgrade() -> None:
    # 0001 pins its table list, so fresh volumes do NOT pre-create this
    # table; this revision owns it (same pattern as 0002-0008).
    op.create_table(
        "sod_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.Integer(),
                  sa.ForeignKey("sod_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("violation_count", sa.Integer(), nullable=False),
        sa.Column("violations", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sod_evaluations_run_id", "sod_evaluations", ["run_id"])
    op.create_index("ix_sod_evaluations_rule_id", "sod_evaluations", ["rule_id"])
def downgrade() -> None:
    op.drop_index("ix_sod_evaluations_rule_id", table_name="sod_evaluations")
    op.drop_index("ix_sod_evaluations_run_id", table_name="sod_evaluations")
    op.drop_table("sod_evaluations")
