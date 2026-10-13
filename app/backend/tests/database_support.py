"""A real Postgres for the data-layer tests: never SQLite, never a mock (CLAUDE.md section 16.4)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final, Self, TextIO

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.config import Settings
from tv_watchlist.data.alembic_support import escaped_url

BACKEND_DIR: Final[Path] = Path(__file__).resolve().parents[1]
# The eleven tables revision 0001 raises. Frozen history rather than a view of the models: a merged
# revision does not grow tables, and `Base.metadata` stopped being the same set the moment 0002 added
# one. Lives here because three suites need it - the offline DDL tests, the 0002 round trip, and the
# metadata test that derives the whole schema from it - and a second copy is the one that drifts.
PHASE_ONE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "category",
        "curated_entry",
        "curated_entry_item",
        "title",
        "season",
        "episode",
        "episode_order",
        "external_id",
        "artwork",
        "watch_event",
        "sync_state",
    }
)
# The two read-only views 0001 raises beside them.
PHASE_ONE_VIEWS: Final[frozenset[str]] = frozenset({"episode_watch_state", "curated_entry_watch_state"})
DATABASE_VARIABLE: Final[str] = "TV_POSTGRES_DB"
DEFAULT_TEST_DATABASE: Final[str] = "tv_test"
# Set in CI (.github/workflows/ci.yml, job test-backend). With it, an unreachable Postgres fails the
# run instead of skipping it, so a mis-wired service container cannot turn the data suite into silence.
REQUIRE_VARIABLE: Final[str] = "TV_REQUIRE_POSTGRES"
# Only a database whose name ends here may be dropped and rebuilt. `tv` is the owner's real projection.
DISPOSABLE_SUFFIX: Final[str] = "_test"
MAINTENANCE_DATABASE: Final[str] = "postgres"
# Long enough for a container that is still warming up, short enough that a whole suite is not held
# hostage by a workstation with no Postgres on it at all.
PROBE_TIMEOUT_SECONDS: Final[float] = 3.0
UNREACHABLE: Final[str] = (
    "no Postgres reachable at {host}:{port} - run `docker compose up -d postgres` or CI's service container"
)
NOT_DISPOSABLE: Final[str] = (
    "{name} is not a disposable test database: the suite rebuilds it from scratch, so {variable} must name "
    "a database ending in {suffix}"
)
# `<stem>_p<pid>_test`. The pid sits before the suffix rather than after it so the name a process owns
# still ends in `_test` and is still refused by the guard above if the stem itself is the owner's `tv`.
_PROCESS_MARK: Final[str] = "_p"
_ABANDONED: Final[re.Pattern[str]] = re.compile(rf"{_PROCESS_MARK}(\d+){re.escape(DISPOSABLE_SUFFIX)}$")


def _configured_name() -> str:
    """Read at call time, never at import, so a fixture or a targeted run may set the variable later."""
    return os.environ.get(DATABASE_VARIABLE, DEFAULT_TEST_DATABASE)


def _stem() -> str:
    return _configured_name().removesuffix(DISPOSABLE_SUFFIX)


def database_name() -> str:
    """The database this pytest process owns: `tv_test` becomes `tv_p<pid>_test`.

    One name shared by two runners is a data race rather than a nuisance. The session start DROPs the
    database it is about to migrate, `WITH (FORCE)`, so a second local run terminates the first one's
    connections and removes its tables from under a suite already in flight - which surfaces as
    `ConnectionDoesNotExistError`, then `UndefinedTableError` on a table the migration had built, then
    a `UniqueViolationError` on `pg_database` when both reach CREATE at once. Folding the pid in is what
    lets two runs share the compose Postgres and nothing else (CLAUDE.md section 16.5).
    """
    configured = _configured_name()
    # Refused here as well as at the DROP: `TV_POSTGRES_DB=tv` must stay a loud error, never a silent
    # rewrite into `tv_p<pid>_test` that leaves the owner unsure which database the suite really ran on.
    require_disposable_database(configured)
    return f"{_stem()}{_PROCESS_MARK}{os.getpid()}{DISPOSABLE_SUFFIX}"


def _process_is_alive(pid: int) -> bool:
    """Signal 0 asks the kernel whether the pid exists, and sends nothing.

    A pid owned by another user answers `PermissionError`, which is still an answer of yes. Refusing to
    reclaim is the cheap mistake here; reclaiming a live run's database is the expensive one.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def settings_for_tests() -> Settings:
    """The environment's Postgres, the owner's .env ignored, the test database name pinned.

    Deliberately not named `test_settings`: this module is importable bare, and pytest would collect a
    zero-argument `test_`-prefixed function as a test that always passes.
    """
    return Settings(_env_file=None, postgres_db=database_name())


def asyncpg_dsn(database_url: str) -> str:
    """asyncpg speaks the plain scheme, not SQLAlchemy's `+asyncpg` one."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def alembic_config(database_url: str, output_buffer: TextIO | None = None) -> Config:
    """An alembic Config with the URL injected the way the app never does: from the harness, not the ini."""
    config = Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=output_buffer)
    config.set_main_option("sqlalchemy.url", escaped_url(database_url))
    return config


@contextmanager
def preserving_root_logging() -> Iterator[None]:
    """env.py's fileConfig rips out the root handlers pytest installed; put them back afterwards."""
    handlers, level = list(logging.root.handlers), logging.root.level
    try:
        yield
    finally:
        logging.root.handlers[:] = handlers
        logging.root.setLevel(level)


async def _connect_to_maintenance(settings: Settings) -> asyncpg.Connection[asyncpg.Record]:
    maintenance = settings.model_copy(update={"postgres_db": MAINTENANCE_DATABASE})
    return await asyncpg.connect(asyncpg_dsn(maintenance.database_url), timeout=PROBE_TIMEOUT_SECONDS)


async def _probe(settings: Settings) -> None:
    connection = await _connect_to_maintenance(settings)
    await connection.close()


def require_reachable_postgres() -> None:
    """Skip, loudly and with the remedy, rather than stand a mock in for the database.

    Only a connection-level failure skips. An authentication or permission error is a misconfigured
    environment, not an absent one, and is left to fail the test it was going to fail anyway.

    `TV_REQUIRE_POSTGRES` turns that skip into a failure. CI sets it, because there a missing database is
    a broken service container, and a suite that quietly skips its whole data layer is worse than a red one.
    """
    settings = settings_for_tests()
    try:
        asyncio.run(_probe(settings))
    except (OSError, TimeoutError) as error:
        reason = UNREACHABLE.format(host=settings.postgres_host, port=settings.postgres_port)
        message = f"{reason} ({type(error).__name__}: {error})"
        if os.environ.get(REQUIRE_VARIABLE):
            pytest.fail(message, pytrace=False)
        pytest.skip(message)


def require_disposable_database(name: str) -> None:
    """Refuse to rebuild anything but a `*_test` database: `tv` holds the owner's real projection."""
    if not name.endswith(DISPOSABLE_SUFFIX):
        raise RuntimeError(NOT_DISPOSABLE.format(name=name, variable=DATABASE_VARIABLE, suffix=DISPOSABLE_SUFFIX))


async def _reclaim_abandoned(connection: asyncpg.Connection[asyncpg.Record]) -> list[str]:
    """Drop every sibling `<stem>_p<pid>_test` whose process is gone, and return what was reclaimed.

    Teardown hands this process's database back, so this only ever finds runs that were killed outright.
    Without it, one name per SIGKILL would accumulate on the compose volume forever - which would trade
    the collision the pid removes for a slow leak, and that is not a trade worth making.
    """
    like = f"{_stem()}{_PROCESS_MARK}%{DISPOSABLE_SUFFIX}"
    reclaimed: list[str] = []
    for row in await connection.fetch("SELECT datname FROM pg_database WHERE datname LIKE $1", like):
        name = str(row[0])
        marked = _ABANDONED.search(name)
        if marked is None or _process_is_alive(int(marked.group(1))):
            continue
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        reclaimed.append(name)
    return reclaimed


async def _recreate_database(settings: Settings) -> None:
    # The guard lives with the DROP, not with the caller: a second caller added later inherits it.
    require_disposable_database(settings.postgres_db)
    connection = await _connect_to_maintenance(settings)
    try:
        await _reclaim_abandoned(connection)
        # Dropped rather than reused: a stale container volume, or a workstation database built by an
        # earlier draft of revision 0001, would otherwise satisfy this suite's schema assertions.
        # DROP/CREATE DATABASE take no bind parameters; the name is a Settings field, not request input,
        # and the guard above has already refused anything but a `*_test` one.
        await connection.execute(f'DROP DATABASE IF EXISTS "{settings.postgres_db}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{settings.postgres_db}"')
    finally:
        await connection.close()


async def _drop_database(settings: Settings) -> None:
    require_disposable_database(settings.postgres_db)
    connection = await _connect_to_maintenance(settings)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{settings.postgres_db}" WITH (FORCE)')
    finally:
        await connection.close()


async def _reclaim(settings: Settings) -> list[str]:
    connection = await _connect_to_maintenance(settings)
    try:
        return await _reclaim_abandoned(connection)
    finally:
        await connection.close()


def reclaim_abandoned_databases() -> list[str]:
    """The sweep on its own, for the test that proves a live run's database survives it."""
    return asyncio.run(_reclaim(settings_for_tests()))


def migrated_database_url() -> str:
    """Rebuild this process's own test database from nothing and bring it to head. Once per session."""
    settings = settings_for_tests()
    asyncio.run(_recreate_database(settings))
    with preserving_root_logging():
        command.upgrade(alembic_config(settings.database_url), "head")
    return settings.database_url


def drop_test_database() -> None:
    """Hand this process's database back when the session ends, so runs leave nothing behind.

    Paired with `migrated_database_url` by the `database_url` fixture, never called on its own: a DROP
    that ran while a test still held a connection would be the very race the pid exists to prevent.
    """
    asyncio.run(_drop_database(settings_for_tests()))


class JoiningSessionFactory:
    """A session factory for code that opens its own session, handing back the test's.

    A background task outlives the request whose session it would otherwise borrow, so the code under
    test takes a factory and opens its own. Under test everything lives inside one rolled-back
    transaction, so the scheduled half has to join it or the rows just written are invisible to it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> Self:
        return self

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_: object) -> None:
        """The fixture owns the session's lifetime; the code under test must not close it."""
        return None
