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
def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
