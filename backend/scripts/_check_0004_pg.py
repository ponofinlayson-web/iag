"""Live fresh-volume proof for migration 0004 on real Postgres 16.

Spins up a throwaway postgres:16-alpine container (NOT the live stack),
runs alembic upgrade head from inside backend/ against it, asserts
schema state, then tears everything down. Complements the SQLite
simulation in _check_0004_fresh.py: same code path, real RDBMS.

Run from backend/:  uv run python scripts/_check_0004_pg.py
"""
import os
import pathlib
import socket
import time

os.environ["IAG_ENV"] = "test"
os.environ["IAG_DATABASE_URL"] = "postgresql+asyncpg://iag:iag@127.0.0.1:55432/iag"
os.environ["IAG_SECRET_KEY"] = "x" * 32

import subprocess  # noqa: E402
import sys  # noqa: E402

CONTAINER = "iag-mig-check-pg"
PW = "iag"
PORT = 55432

sh = lambda cmd: subprocess.run(  # noqa: E731
    cmd, shell=True, capture_output=True, text=True
)

print("[1/5] starting throwaway postgres on :55432 ...")
sh(f"docker rm -f {CONTAINER}")
r = sh(f"docker run -d --name {CONTAINER} -e POSTGRES_PASSWORD={PW} "
       f"-e POSTGRES_USER=iag -e POSTGRES_DB=iag -p 127.0.0.1:{PORT}:5432 postgres:16-alpine")
if r.returncode != 0:
    print("docker run failed:", r.stderr)
    sys.exit(1)

try:
    # wait for readiness
    for i in range(30):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                break
        except OSError:
            time.sleep(1)
    else:
        print("postgres never came up")
        sys.exit(1)
    time.sleep(2)  # TCP up != accepting queries
    for i in range(30):
        r = sh(f"docker exec {CONTAINER} pg_isready -U iag")
        if "accepting connections" in r.stdout:
            break
        time.sleep(1)

    print("[2/5] alembic upgrade head on FRESH postgres ...")
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")

    print("[3/5] verifying schema ...")
    import sqlalchemy as sa

    eng = sa.create_engine(f"postgresql+psycopg2://iag:{PW}@127.0.0.1:{PORT}/iag")
    insp = sa.inspect(eng)
    src_cols = {c["name"] for c in insp.get_columns("data_sources")}
    need = {"connector_config", "connector_secret", "sync_interval_minutes",
            "next_sync_at", "last_sync_at"}
    assert need <= src_cols, need - src_cols
    assert insp.has_table("sync_runs"), "sync_runs missing"
    idx = [i["name"] for i in insp.get_indexes("sync_runs")]
    assert "uq_sync_run_inflight" in idx, idx
    with eng.connect() as c:
        ver = c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert ver == "0004", ver
    print("    version =", ver, "| 5 cols + sync_runs + partial index OK")

    print("[4/5] downgrade -> 0003 ...")
    command.downgrade(cfg, "0003")
    eng.dispose()
    eng2 = sa.create_engine(f"postgresql+psycopg2://iag:{PW}@127.0.0.1:{PORT}/iag")
    insp2 = sa.inspect(eng2)
    cols2 = {c["name"] for c in insp2.get_columns("data_sources")}
    assert "connector_config" not in cols2
    with eng2.connect() as c:
        ver2 = c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert ver2 == "0003", ver2
    eng2.dispose()
    print("    downgrade verified: 0003, cols dropped")
finally:
    print("[5/5] teardown ...")
    sh(f"docker rm -f {CONTAINER}")
    p = pathlib.Path("_scratch_fresh.db")
    if p.exists():
        p.unlink()
print("PG FRESH-VOLUME PROOF: PASS")
