"""initial schema
Revision ID: 0001
Revises:
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app.models import *  # noqa: F401,F403 - register all models on Base.metadata
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None
# All tables created from Base.metadata at build time; portable column types
# only (Integer/String/Text/Boolean/DateTime/Enum), verified to render
# identically on SQLite and Postgres.
# PINNED table set: this revision predates every table added later. Letting
# create_all see the full current metadata would also build those tables,
# and the migration that owns them (0002+) would then fail with
# DuplicateTable on a fresh volume. Each revision owns its own tables.
V1_TABLES = (
    "identities", "users", "data_sources", "accounts", "entitlements",
    "campaigns", "reviews", "audit_entries",
)
def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in V1_TABLES])
def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in V1_TABLES])
