"""feature 2: connector config columns + sync_runs table
Revision ID: 0004
Revises: 0003
Create Date: 2026-08-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_INFLIGHT = sa.text("status IN ('pending', 'syncing')")


def upgrade() -> None:
    # data_sources columns are GUARDED, not blind-added: 0001 builds tables
    # from CURRENT metadata (create_all), so on a fresh volume they already
    # exist by the time this revision runs and a plain add_column would die
    # with duplicate-column. Existing volumes get them added here. Both
    # paths proven in scripts/_check_0004_fresh.py.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("data_sources")}
    _NEW_COLS = (
        sa.Column("connector_config", sa.Text(), nullable=True),
        # Plaintext by USER DECISION 2026-08-20 (D2 deferred); see spec Secrets.
        sa.Column("connector_secret", sa.Text(), nullable=True),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
    )
    for col in _NEW_COLS:
        if col.name not in existing:
            op.add_column("data_sources", col)
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_source_id", sa.Integer(),
                  sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("triggered_by", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("stats", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sync_runs_data_source_id", "sync_runs", ["data_source_id"])
    op.create_index(
        "uq_sync_run_inflight", "sync_runs", ["data_source_id"], unique=True,
        postgresql_where=_INFLIGHT, sqlite_where=_INFLIGHT,
    )


def downgrade() -> None:
    op.drop_index("uq_sync_run_inflight", table_name="sync_runs")
    op.drop_index("ix_sync_runs_data_source_id", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_column("data_sources", "last_sync_at")
    op.drop_column("data_sources", "next_sync_at")
    op.drop_column("data_sources", "sync_interval_minutes")
    op.drop_column("data_sources", "connector_secret")
    op.drop_column("data_sources", "connector_config")
