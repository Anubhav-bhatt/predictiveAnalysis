"""Async engine and session management.

Both runtimes - the FastAPI process and the ingestion worker - build sessions
through this module, but they do so with different pool characteristics: the API
serves many short requests, the worker runs a few long transactions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.config import DatabaseSettings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def build_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Create an engine appropriate for the configured backend."""
    kwargs: dict[str, object] = {"echo": settings.echo, "future": True}
    if not settings.is_sqlite:
        # SQLite (tests) rejects these pool arguments.
        kwargs.update(
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_pre_ping=True,
        )
    return create_async_engine(settings.async_url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().database)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for worker/CLI code.

    Commits on clean exit, rolls back on any exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


async def dispose_engine() -> None:
    """Release pooled connections; called on API shutdown and after CLI runs."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine_cache() -> None:
    """Drop cached engine/factory so a new configuration takes effect (tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
