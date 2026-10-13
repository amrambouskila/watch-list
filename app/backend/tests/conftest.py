"""Shared fixtures: every test runs against throwaway copies of the real workbooks."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from database_support import drop_test_database, migrated_database_url, require_reachable_postgres
from library_choice import a_category, library_workbooks
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook import backup
from workbook_facts import WorkbookFacts


@pytest.fixture(scope="session", autouse=True)
def declared_env_file() -> Iterator[Path | None]:
    """The `env_file` the class declares, lifted out of `model_config` for the whole run and yielded."""
    # `get_settings()` takes no arguments, so `_env_file=None` at a call site cannot protect the paths
    # that reach it - `create_app()` and `get_engine()` both do. Only the class config keeps the owner's
    # real root .env, which holds live TMDB and TheTVDB credentials, out of the test process.
    declared = Settings.model_config["env_file"]
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()
    yield declared
    Settings.model_config["env_file"] = declared
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_backup_state() -> Iterator[None]:
    backup.reset()
    yield
    backup.reset()


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A disposable copy of the whole library."""
    destination = tmp_path / "library"
    destination.mkdir()
    for path in library_workbooks():
        shutil.copy2(path, destination / path.name)
    return destination


@pytest.fixture
def settings(library: Path, tmp_path: Path) -> Settings:
    """Settings for one test. `_env_file=None`: the owner's root .env never reaches a test."""
    return Settings(
        _env_file=None, library_dir=library, backup_dir=tmp_path / "backups", heroes_dir=tmp_path / "heroes"
    )


@pytest.fixture
def catalog(settings: Settings) -> Catalog:
    return Catalog(settings)


@pytest.fixture
def subject(library: Path) -> WorkbookFacts:
    """The default category a test writes to, chosen by shape and copied into the throwaway library."""
    return a_category()


@pytest.fixture
def subject_path(subject: WorkbookFacts, library: Path) -> Path:
    """The disposable copy of that category's workbook."""
    return subject.copied_into(library)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """This process's own migrated test database, handed back when the session ends.

    Sync and session-scoped: env.py runs its own asyncio.run. The name carries the pid, so a second
    local run gets its own database rather than dropping this one mid-suite (CLAUDE.md section 16.5).
    """
    # Skipping is the only honest answer when nothing is listening: a mock database would prove that the
    # mock agrees with itself (CLAUDE.md section 16.4).
    require_reachable_postgres()
    url = migrated_database_url()
    try:
        yield url
    finally:
        drop_test_database()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Function-scoped on a NullPool, so no connection outlives the event loop of the test that opened it."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Everything a test writes is rolled back: the outer transaction is never committed.

    `create_savepoint` makes a `session.commit()` inside a test release a SAVEPOINT rather than the outer
    transaction, so code under test may commit and the database is still clean afterwards.
    """
    # Skips with `database_url` when nothing is listening, so a workstation with no Postgres reports a
    # loud skip rather than a mocked pass (CLAUDE.md section 16.4).
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
