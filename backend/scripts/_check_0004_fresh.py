"""Prove/disprove: does 0001-create_all-with-current-metadata + 0004 add_column
collide on a fresh database? Scratch SQLite file, real alembic code path.

Run from backend/:  uv run python scripts/_check_0004_fresh.py
"""
import os
import pathlib

os.environ["IAG_ENV"] = "test"
os.environ["IAG_DATABASE_URL"] = "sqlite+aiosqlite:///./_scratch_fresh.db"
if not os.environ.get("IAG_SECRET_KEY"):
    os.environ["IAG_SECRET_KEY"] = "x" * 32

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

scratch = pathlib.Path("_scratch_fresh.db")
if scratch.exists():
    scratch.unlink()

cfg = Config("alembic.ini")
cfg.set_main_option("script_location", "alembic")
command.upgrade(cfg, "head")
print("UPGRADE TO HEAD ON FRESH DB: OK")

from sqlalchemy import create_engine, inspect  # noqa: E402

eng = create_engine("sqlite:///./_scratch_fresh.db")
insp = inspect(eng)
cols = [c["name"] for c in insp.get_columns("data_sources")]
print("data_sources cols:", sorted(cols))
assert "connector_config" in cols and "sync_interval_minutes" in cols
print("sync_runs present:", insp.has_table("sync_runs"))
assert insp.has_table("sync_runs")
command.downgrade(cfg, "0003")
print("DOWNGRADE 0004 -> 0003: OK")
# Inspector caches schema info — re-inspect with a fresh cache, not the
# pre-downgrade snapshot.
insp2 = inspect(eng)
cols2 = [c["name"] for c in insp2.get_columns("data_sources")]
assert "connector_config" not in cols2, cols2
print("fresh-volume simulation complete: no DuplicateColumn, downgrade clean")
