"""Database access for business tables (SQLAlchemy async + asyncpg).

The LangGraph checkpointer (see graphs.py) shares the same Postgres database
but manages its own tables; this module only owns the business schema.
"""

import logging
import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all business tables."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def database_url() -> str | None:
    """AsyncPG-style DSN from the environment, or None when not configured."""
    return os.environ.get("DATABASE_URL") or None


def checkpointer_dsn() -> str | None:
    """DSN for AsyncPostgresSaver, which speaks plain postgres:// (psycopg)."""
    url = database_url()
    return url.replace("+asyncpg", "") if url else None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory, raising if startup never initialized the engine."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized; DATABASE_URL missing or startup failed")
    return _session_factory


async def init_engine() -> bool:
    """Create the engine and session factory. Returns True when a DB is reachable."""
    global _engine, _session_factory
    
    url = database_url()
    if not url:
        logger.warning("DATABASE_URL is not set; persistence endpoints will be unavailable")
        return False

    _engine = create_async_engine(url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Dev convenience (AUTH_MODE=local): create tables from ORM metadata so the
    # server works without running Alembic first. Production must use migrations.
    if os.environ.get("AUTH_MODE", "local") == "local":
        from server import models  # noqa: F401  (ensure tables are registered)

        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Business tables ensured via create_all (dev mode, no alembic_version "
            "stamp). If you later adopt migrations on this database, run: "
            "alembic stamp head  (then alembic upgrade head for new revisions)")
    return True


async def close_engine() -> None:
    """Dispose the engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
