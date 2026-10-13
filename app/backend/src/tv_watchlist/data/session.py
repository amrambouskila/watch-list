"""The async engine, the session factory, and the FastAPI dependency that hands out one session per request."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from tv_watchlist.config import get_settings


def build_engine(database_url: str) -> AsyncEngine:
    """An engine on the one asyncpg URL the project has. Connects lazily; building one touches no socket."""
    return create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """`expire_on_commit=False` so a committed instance can still be read into a Pydantic model without a lazy load."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Process-wide engine; disposed by the app lifespan."""
    return build_engine(get_settings().database_url)


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Process-wide session factory, bound to the process-wide engine."""
    return build_session_factory(get_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request, closed when the request ends."""
    async with get_session_factory()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
