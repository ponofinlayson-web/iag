"""Database engine and session management.
Async engine for the app; sync URL helper for Alembic/tests. Uses only
portable column types so the same models run on SQLite (tests) and
Postgres (production) without dialect-specific branches.
"""
from __future__ import annotations
from collections.abc import AsyncIterator
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from app.core.settings import Settings
_settings = Settings()
class Base(DeclarativeBase):
    pass
def build_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        return create_async_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_async_engine(database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
engine: AsyncEngine = build_engine(_settings.database_url)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
@event.listens_for(Engine, "connect")
def _fk_pragma(dbapi_connection, connection_record):
    """SQLite: enforce FKs so tests exercise the same delete semantics as Postgres."""
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
