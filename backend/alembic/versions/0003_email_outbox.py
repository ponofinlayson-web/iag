"""email outbox table
Revision ID: 0003
Revises: 0002
Create Date: 2026-08-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(),
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_id", sa.Integer(),
                  sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("review_id", name="uq_email_outbox_review"),
    )
    op.create_index("ix_email_outbox_status_due", "email_outbox", ["status", "due_at"])
    op.create_index("ix_email_outbox_campaign_id", "email_outbox", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_email_outbox_campaign_id", table_name="email_outbox")
    op.drop_index("ix_email_outbox_status_due", table_name="email_outbox")
    op.drop_table("email_outbox")
