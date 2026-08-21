"""feature 4: api_keys table
Revision ID: 0006
Revises: 0005
Create Date: 2026-08-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 pins its table list, so fresh volumes do NOT pre-create this
    # table; this revision owns it (same pattern as 0002-0005).
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        # native_enum=False: plain VARCHAR on every dialect. The PG enum
        # TYPE "role" already exists (0001 created it for users.role) and
        # sa.Enum inside create_table would try CREATE TYPE and collide.
        sa.Column("role", sa.Enum("system_admin", "certification_admin", "reviewer",
                                  "auditor", "report_viewer", name="role",
                                  native_enum=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # Model declares key_hash unique+indexed; create_all emits a UNIQUE
    # INDEX named ix_api_keys_key_hash, so mirror that exactly (a column
    # UNIQUE constraint + separate index would diverge from test schema).
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
