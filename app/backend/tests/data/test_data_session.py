from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lifespan_support import run_lifespan
from tv_watchlist import main
from tv_watchlist.data.session import (
    build_engine,
    build_session_factory,
    get_engine,
    get_session,
    get_session_factory,
)

A_URL = "postgresql+asyncpg://tv:tv@localhost:5525/tv_test"


def test_build_engine_returns_an_async_engine_without_connecting() -> None:
    engine = build_engine(A_URL)
    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
    # Neither checked out nor idle in the pool: nothing has dialled 5525, which is what lets this whole
    # suite run with no Postgres on the machine.
    assert (engine.pool.checkedout(), engine.pool.checkedin()) == (0, 0)


def test_the_session_factory_never_expires_on_commit_and_never_autoflushes() -> None:
    factory = build_session_factory(build_engine(A_URL))
    assert isinstance(factory, async_sessionmaker)
    assert factory.kw["expire_on_commit"] is False
    assert factory.kw["autoflush"] is False


def test_get_engine_is_a_process_singleton() -> None:
    assert get_engine() is get_engine()


def test_get_session_factory_is_a_process_singleton_over_that_engine() -> None:
    factory = get_session_factory()
    assert factory is get_session_factory()
    assert factory.kw["bind"] is get_engine()


async def test_get_session_yields_one_session_and_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    class _Session(AsyncSession):
        async def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        "tv_watchlist.data.session.get_session_factory",
        lambda: async_sessionmaker(build_engine(A_URL), class_=_Session, expire_on_commit=False, autoflush=False),
    )
    sessions: AsyncIterator[AsyncSession] = get_session()
    session = await anext(sessions)
    assert isinstance(session, _Session)
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)
    assert closed == [True]


async def test_the_lifespan_closes_the_agent_runtime_then_disposes_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In that order: a chat turn still in flight holds a session, so the pool goes last."""
    shutdown: list[str] = []

    class _Engine:
        async def dispose(self) -> None:
            shutdown.append("engine")

    class _Runtime:
        async def aclose(self) -> None:
            shutdown.append("runtime")

    monkeypatch.setattr(main, "get_engine", lambda: _Engine())
    monkeypatch.setattr(main, "get_agent_runtime", lambda: _Runtime())
    app: FastAPI = main.create_app()
    await run_lifespan(app)
    assert shutdown == ["runtime", "engine"]


def test_session_dep_is_the_fastapi_dependency() -> None:
    from tv_watchlist.data.session import SessionDep

    metadata: tuple[object, ...] = SessionDep.__metadata__
    assert getattr(metadata[0], "dependency", None) is get_session
