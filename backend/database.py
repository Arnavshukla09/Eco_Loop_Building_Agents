"""
backend/database.py
───────────────────
Asynchronous database engine and session management using SQLAlchemy 2.0.
Supports SQLite (local dev/test via aiosqlite) and PostgreSQL (production).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from config.settings import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = settings.DATABASE_URL
        # If using local SQLite, ensure the directory exists
        if "sqlite" in db_url:
            raw_path = db_url.split("///")[-1]
            if raw_path and raw_path != ":memory:":
                db_path = Path(raw_path)
                db_path.parent.mkdir(parents=True, exist_ok=True)

        _engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
        )
        logger.info("Database engine initialised for %s", db_url.split("@")[-1])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all database tables if they do not exist."""
    import backend.db_models  # Ensure models are imported so Base.metadata knows about them
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema verified and created.")


async def close_db() -> None:
    """Dispose the database connection pool on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection pool closed.")
