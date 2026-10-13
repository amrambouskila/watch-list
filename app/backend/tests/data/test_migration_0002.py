"""Phase 3's first revision, and ONLY what it emits: `jellyfin_item`, the pick column, and their enum.

The chain's own round trip - up, down, up, `alembic check`, every type gone at base - is
`test_migration_round_trip.py` beside this, and nothing here repeats it. What is left is the half a
migrated database cannot show: the ORDER of one revision's statements, and the foreign-key action only
Postgres's own catalogue can be asked for.

Autogenerate got two things wrong here and both are ordering. It declared the enum inline with
SQLAlchemy's `create_type=True` - not how this schema creates types, since `pg_enum` sets it False - and
its `downgrade` dropped the table while leaving the type behind, which fails the NEXT `upgrade head` on
"type already exists" while a single-step `downgrade -1` looks perfectly clean.
"""

from __future__ import annotations

import asyncio
import io
from functools import lru_cache
from typing import Final

import asyncpg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from database_support import alembic_config, asyncpg_dsn, preserving_root_logging

JELLYFIN_TABLE: Final[str] = "jellyfin_item"
JELLYFIN_ENUM: Final[str] = "jellyfin_item_kind"
PICK_COLUMN: Final[str] = "jellyfin_item_id"
PICK_FK: Final[str] = "fk_title_jellyfin_item_id_jellyfin_item"
# Offline mode needs a dialect to compile against; nothing connects and nothing lives at this address.
OFFLINE_URL: Final[str] = "postgresql+asyncpg://tv:tv@127.0.0.1:5599/tv_offline"

_TITLE_COLUMNS: Final[str] = "SELECT column_name FROM information_schema.columns WHERE table_name = 'title'"
# The foreign key's own action, read off the catalogue rather than off the model that declared it.
# A literal, not an f-string over PICK_FK: interpolating a name into SQL is the shape ruff's S608
# refuses on sight, and it is right to - a catalogue query is not the place to make an exception.
_PICK_FK_ACTION: Final[str] = """
SELECT confdeltype::text
  FROM pg_constraint
 WHERE conname = 'fk_title_jellyfin_item_id_jellyfin_item'
"""


async def _query(database_url: str, sql: str) -> set[str]:
    connection = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        return {str(row[0]) for row in await connection.fetch(sql)}
    finally:
        await connection.close()


def _rows(database_url: str, sql: str) -> set[str]:
    return asyncio.run(_query(database_url, sql))


def _at_head(config: Config) -> None:
    """A no-op when the session is already there, and what makes this file independent of test order."""
    with preserving_root_logging():
        command.upgrade(config, "head")


@lru_cache(maxsize=2)
def _this_revision_sql(*, upgrade: bool) -> str:
    """Just this revision's own statements, rendered without a database.

    The range is read off the chain rather than written down (R62), and it names THIS revision rather
    than the head: the one whose parent is the base. `base:head` was the same pair only while this was the
    newest revision, and the next task to add one would have silently turned this into a test of that.
    """
    script = ScriptDirectory.from_config(alembic_config(OFFLINE_URL))
    base = script.get_base()
    mine = next(revision for revision in script.walk_revisions() if revision.down_revision == base)
    buffer = io.StringIO()
    config = alembic_config(OFFLINE_URL, output_buffer=buffer)
    with preserving_root_logging():
        if upgrade:
            command.upgrade(config, f"{base}:{mine.revision}", sql=True)
        else:
            command.downgrade(config, f"{mine.revision}:{base}", sql=True)
    return buffer.getvalue()


def test_the_offline_sql_builds_the_type_the_table_and_the_pick_then_unwinds_them_in_order() -> None:
    """Everything this revision emits, in the order it emits it - the half a migrated database cannot show."""
    up = _this_revision_sql(upgrade=True)
    down = _this_revision_sql(upgrade=False)

    # The type is created by hand, before the table whose column is declared with it. `pg_enum` sets
    # `create_type=False`, so nothing else in this revision would ever create it.
    assert up.index(f"CREATE TYPE {JELLYFIN_ENUM} AS ENUM ('movie', 'series', 'episode')") < up.index(
        f"CREATE TABLE {JELLYFIN_TABLE}"
    )
    # The upsert key, and the CHECK that keeps a zero-tick runtime out.
    assert "CONSTRAINT uq_jellyfin_item_jellyfin_id UNIQUE (jellyfin_id)" in up
    assert "CHECK (run_time_seconds IS NULL OR run_time_seconds > 0)" in up
    # The pick lands on title AFTER the table it references, and it is SET NULL rather than CASCADE.
    assert up.index(f"CREATE TABLE {JELLYFIN_TABLE}") < up.index(f"ALTER TABLE title ADD COLUMN {PICK_COLUMN}")
    assert (
        f"ADD CONSTRAINT {PICK_FK} FOREIGN KEY({PICK_COLUMN}) REFERENCES {JELLYFIN_TABLE} (id) ON DELETE SET NULL" in up
    )

    # The hand-ordered downgrade: the constraint and the column go before the table, and the type goes
    # last. Autogenerate emitted neither the type's creation nor its drop.
    assert down.index(f"DROP CONSTRAINT {PICK_FK}") < down.index(f"DROP COLUMN {PICK_COLUMN}")
    assert down.index(f"DROP COLUMN {PICK_COLUMN}") < down.index(f"DROP TABLE {JELLYFIN_TABLE}")
    assert down.index(f"DROP TABLE {JELLYFIN_TABLE}") < down.index(f"DROP TYPE {JELLYFIN_ENUM}")
    # And nothing of Phase 1's is touched by either direction.
    assert "DROP TABLE title" not in down
    assert "watch_event" not in up


def test_the_pick_column_lands_on_title_with_set_null(database_url: str) -> None:
    """Read off `pg_constraint`, because the action is the database's and only it can be asked."""
    _at_head(alembic_config(database_url))

    assert PICK_COLUMN in _rows(database_url, _TITLE_COLUMNS)
    # 'n' is SET NULL in pg_constraint.confdeltype; 'c' would be CASCADE and 'r' RESTRICT.
    assert _rows(database_url, _PICK_FK_ACTION) == {"n"}
