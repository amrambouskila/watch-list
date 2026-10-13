"""The gate in `docs/TV_MASTER_PLAN.md` 10.1: up, all the way down, up again - for the WHOLE chain.

This is the one chain-wide home, and it is named for the claim rather than for a revision on purpose: the
gate and CI both point at "the round trip", and every revision-named file beside it
(`test_migration_0002.py`, and whatever 0003 brings) asserts only what its own revision emits. Nothing
here is repeated there, and nothing there is repeated here.

A single-step `downgrade -1` proves none of it. The views must drop before the tables they read, the
append-only trigger before `watch_event`, a later revision's foreign-key column before the table it
references, and every native enum after all of them - and autogenerate orders not one of the four. Each
failure appears only on the second pass, which is why the trip is down-up-down-up rather than down-up.

Revision ids appear nowhere below. The head is read off the chain, and the table set is the shared one
from `database_support`, so the next revision adds a name there and edits nothing here.
"""

from __future__ import annotations

import asyncio
from typing import Final

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import ENUM

from database_support import (
    PHASE_ONE_TABLES,
    PHASE_ONE_VIEWS,
    alembic_config,
    asyncpg_dsn,
    preserving_root_logging,
)
from tv_watchlist.data.base import Base

# Every table the chain raises: Phase 1's eleven plus what each later revision added. T55's
# `streaming_offer` joins this line when its revision lands.
CHAIN_TABLES: Final[frozenset[str]] = PHASE_ONE_TABLES | {
    "jellyfin_item",
    "media_import",
    "media_import_operation",
    "playback_completion",
    "playback_completion_event",
}
# Offline mode needs a dialect to compile against; nothing connects and nothing lives at this address.
OFFLINE_URL: Final[str] = "postgresql+asyncpg://tv:tv@127.0.0.1:5599/tv_offline"

_TABLES: Final[str] = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
_VIEWS: Final[str] = "SELECT viewname FROM pg_views WHERE schemaname = 'public'"
_ENUM_TYPES: Final[str] = "SELECT typname FROM pg_type WHERE typtype = 'e'"


async def _query(database_url: str, sql: str) -> set[str]:
    connection = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        return {str(row[0]) for row in await connection.fetch(sql)}
    finally:
        await connection.close()


def _rows(database_url: str, sql: str) -> set[str]:
    return asyncio.run(_query(database_url, sql))


def _every_enum_type() -> set[str]:
    """Every native enum the models declare, so a type added later is covered without editing this file."""
    return {
        column.type.name
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, ENUM) and column.type.name is not None
    }


def _at_head(config: Config, database_url: str) -> None:
    """Leave the database where every other test in the session expects to find it."""
    with preserving_root_logging():
        command.upgrade(config, "head")


def test_the_chain_has_exactly_one_head() -> None:
    """Read off `ScriptDirectory`, so a branch is a failure here rather than a surprise in a deploy."""
    assert len(ScriptDirectory.from_config(alembic_config(OFFLINE_URL)).get_heads()) == 1


def test_upgrade_head_downgrade_base_upgrade_head_is_a_clean_round_trip(database_url: str) -> None:
    config = alembic_config(database_url)

    with preserving_root_logging():
        command.downgrade(config, "base")
        assert _rows(database_url, _TABLES) & CHAIN_TABLES == set()
        assert _rows(database_url, _VIEWS) & PHASE_ONE_VIEWS == set()
        # Every type, not a sample: one left behind is what makes the NEXT upgrade fail, and it fails on
        # "type already exists" several revisions away from whichever downgrade actually forgot it.
        assert _rows(database_url, _ENUM_TYPES) & _every_enum_type() == set()

        command.upgrade(config, "head")
        assert CHAIN_TABLES <= _rows(database_url, _TABLES)
        assert PHASE_ONE_VIEWS <= _rows(database_url, _VIEWS)
        assert _every_enum_type() <= _rows(database_url, _ENUM_TYPES)

        # Down and up again, because the ordering failures this guards against appear on the second pass.
        command.downgrade(config, "base")
        command.upgrade(config, "head")

    assert CHAIN_TABLES <= _rows(database_url, _TABLES)
    assert PHASE_ONE_VIEWS <= _rows(database_url, _VIEWS)


def test_a_migrated_database_holds_the_chains_tables_and_nothing_else(database_url: str) -> None:
    """Alembic's own bookkeeping table is the only thing in `public` the models do not declare."""
    _at_head(alembic_config(database_url), database_url)

    assert _rows(database_url, _TABLES) == CHAIN_TABLES | {"alembic_version"}


def test_the_models_and_the_migrations_describe_the_same_schema(database_url: str) -> None:
    """`alembic check` raises AutogenerateDiffsDetected on any drift.

    A hard gate with no tolerance for partial-index noise, only because T08 already pasted Postgres's own
    deparsed predicate into both the models and the revision. If it goes red on an index, the fix is that
    alignment, never a loosened assertion here.
    """
    config = alembic_config(database_url)
    _at_head(config, database_url)

    with preserving_root_logging():
        command.check(config)
