"""Revision 0003, and ONLY what it emits: `media_import`, its three enums, and the FK ordering they force.

The chain's own round trip - up, down, up, `alembic check`, every type gone at base - is
`test_migration_round_trip.py` beside this, and nothing here repeats it. What is left is the half a
migrated database cannot show: the ORDER of one revision's statements, and the foreign-key actions only
Postgres's own catalogue can be asked for.

Autogenerate would get the same two things wrong here that it got wrong in 0002: it declares each enum
inline with SQLAlchemy's own `create_type=True` - not how this schema creates types, since `pg_enum` sets
it False - and it would drop the table while leaving the three types behind, which fails the NEXT
`upgrade head` on "type already exists" while a single-step `downgrade -1` looks perfectly clean.
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

TABLE: Final[str] = "media_import"
SOURCE_ENUM: Final[str] = "media_import_source"
IDENTIFIED_BY_ENUM: Final[str] = "media_import_identified_by"
STATUS_ENUM: Final[str] = "media_import_status"
# Offline mode needs a dialect to compile against; nothing connects and nothing lives at this address.
OFFLINE_URL: Final[str] = "postgresql+asyncpg://tv:tv@127.0.0.1:5599/tv_offline"

# The three FKs this revision's ordering exists for: `jellyfin_item_id` is the one that forces this
# revision to follow T49's (0002), never precede it; `superseded_by_id` is the one self-referencing FK.
_TITLE_FK: Final[str] = "fk_media_import_title_id_title"
_EPISODE_FK: Final[str] = "fk_media_import_episode_id_episode"
_JELLYFIN_FK: Final[str] = "fk_media_import_jellyfin_item_id_jellyfin_item"
_SUPERSEDED_FK: Final[str] = "fk_media_import_superseded_by_id_media_import"
# A literal, not an f-string over a constraint name: interpolating a name into SQL is the shape ruff's
# S608 refuses on sight, and a catalogue query is not the place to make an exception.
_FK_ACTION: Final[str] = """
SELECT conname, confdeltype::text
  FROM pg_constraint
 WHERE conname = ANY($1::text[])
"""


async def _fk_actions(database_url: str, names: list[str]) -> dict[str, str]:
    connection = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        records = await connection.fetch(_FK_ACTION, names)
        return {str(record["conname"]): str(record["confdeltype"]) for record in records}
    finally:
        await connection.close()


def _actions(database_url: str, names: list[str]) -> dict[str, str]:
    return asyncio.run(_fk_actions(database_url, names))


def _at_head(config: Config) -> None:
    """A no-op when the session is already there, and what makes this file independent of test order."""
    with preserving_root_logging():
        command.upgrade(config, "head")


@lru_cache(maxsize=2)
def _this_revision_sql(*, upgrade: bool) -> str:
    """Just this revision's own statements, rendered without a database.

    The range is read off the chain rather than written down (R62), and it names THIS revision - the one
    whose `down_revision` is 0002 - rather than the head, so a later task adding 0004 does not silently
    turn this into a test of that one instead.
    """
    script = ScriptDirectory.from_config(alembic_config(OFFLINE_URL))
    mine = next(revision for revision in script.walk_revisions() if revision.down_revision == "0002")
    buffer = io.StringIO()
    config = alembic_config(OFFLINE_URL, output_buffer=buffer)
    with preserving_root_logging():
        if upgrade:
            command.upgrade(config, f"0002:{mine.revision}", sql=True)
        else:
            command.downgrade(config, f"{mine.revision}:0002", sql=True)
    return buffer.getvalue()


def test_the_offline_sql_creates_the_three_types_before_the_table_and_unwinds_them_after() -> None:
    """Everything this revision emits, in the order it emits it - the half a migrated database cannot show."""
    up = _this_revision_sql(upgrade=True)
    down = _this_revision_sql(upgrade=False)

    # Every type is created by hand, before the table whose columns are declared with it. `pg_enum` sets
    # `create_type=False`, so nothing else in this revision would ever create one.
    table_at = up.index(f"CREATE TABLE {TABLE}")
    assert up.index(f"CREATE TYPE {SOURCE_ENUM} AS ENUM") < table_at
    assert up.index(f"CREATE TYPE {IDENTIFIED_BY_ENUM} AS ENUM") < table_at
    assert up.index(f"CREATE TYPE {STATUS_ENUM} AS ENUM") < table_at
    assert f"CREATE TYPE {STATUS_ENUM} AS ENUM ('found', 'identified', 'moved', 'hashed', 'refreshed', " in up

    # The partial unique index that makes `duplicate_skipped` a database fact rather than a service
    # convention - and the two CHECKs that are easiest to get backwards.
    assert (
        "CREATE UNIQUE INDEX ix_media_import_live_sha256 ON media_import (file_sha256) WHERE "
        "file_sha256 IS NOT NULL AND superseded_at IS NULL AND status IN ('moved', 'hashed', 'refreshed')" in up
    )
    assert "CHECK (size_bytes > 0)" in up
    assert "CHECK (superseded_by_id IS NULL OR superseded_by_id <> id)" in up
    # Ruling 100 (fix round 1): renamed from `identified_has_title`, and re-pointed at `identified_by` -
    # a column no parent delete can touch - rather than `title_id`, which the FK's own SET NULL must be
    # free to null without this CHECK fighting it.
    assert (
        "CONSTRAINT ck_media_import_identified_records_how CHECK "
        "(status IN ('found', 'unidentified', 'failed') OR identified_by IS NOT NULL)" in up
    )
    assert "identified_has_title" not in up
    assert "title_id IS NOT NULL" not in up

    # The hand-ordered downgrade: the table goes before all three types, never after even one of them.
    drop_table_at = down.index(f"DROP TABLE {TABLE}")
    assert drop_table_at < down.index(f"DROP TYPE {STATUS_ENUM}")
    assert drop_table_at < down.index(f"DROP TYPE {IDENTIFIED_BY_ENUM}")
    assert drop_table_at < down.index(f"DROP TYPE {SOURCE_ENUM}")
    # And nothing of an earlier revision's is touched by either direction.
    assert "DROP TABLE title" not in down
    assert "DROP TABLE jellyfin_item" not in down
    assert "watch_event" not in up


def test_every_parent_may_vanish_without_taking_the_row_with_it(database_url: str) -> None:
    """Read off `pg_constraint`, because the action is the database's and only it can be asked."""
    _at_head(alembic_config(database_url))

    actions = _actions(database_url, [_TITLE_FK, _EPISODE_FK, _JELLYFIN_FK])
    # 'n' is SET NULL in pg_constraint.confdeltype; 'c' would be CASCADE and 'r' RESTRICT.
    assert actions == {_TITLE_FK: "n", _EPISODE_FK: "n", _JELLYFIN_FK: "n"}


def test_a_superseding_row_may_not_be_removed_while_something_points_at_it(database_url: str) -> None:
    """The one self-referencing FK is RESTRICT, never SET NULL or CASCADE - a superseding row is load-bearing."""
    _at_head(alembic_config(database_url))

    assert _actions(database_url, [_SUPERSEDED_FK]) == {_SUPERSEDED_FK: "r"}
