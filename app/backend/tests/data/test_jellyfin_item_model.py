"""`jellyfin_item`, and the one column it adds to `title`.

The shape assertions are offline - a naming convention and a nullability are properties of the metadata.
The three that matter most are not: a unique that Postgres enforces, a soft delete that leaves the
owner's pick standing, and an `ON DELETE SET NULL` that only a real foreign key can be asked to perform.
"""

from __future__ import annotations

import uuid
from typing import Final

import pytest
from sqlalchemy import CheckConstraint, Index, Integer, String, UniqueConstraint, delete, select
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.data.base import Base
from tv_watchlist.data.enums import JellyfinItemKind, MediaType
from tv_watchlist.data.models import JellyfinItem, Title

A_JELLYFIN_ID: Final[str] = "0a1b2c3d4e5f6071829304a5b6c7d8e9"
ANOTHER_JELLYFIN_ID: Final[str] = "1b2c3d4e5f60718293a4b5c6d7e8f901"
IRON_MAN_TMDB_ID: Final[int] = 1726
TABLE: Final[str] = "jellyfin_item"


def _item(jellyfin_id: str = A_JELLYFIN_ID, **overrides: object) -> JellyfinItem:
    values: dict[str, object] = {
        "jellyfin_id": jellyfin_id,
        "kind": JellyfinItemKind.MOVIE,
        "name": "Iron Man",
        "tmdb_id": IRON_MAN_TMDB_ID,
    }
    values.update(overrides)
    return JellyfinItem(**values)


def _a_title(**overrides: object) -> Title:
    values: dict[str, object] = {
        "media_type": MediaType.MOVIE,
        "tmdb_id": IRON_MAN_TMDB_ID,
        "name": "Iron Man",
        "match_key": "iron man 2008",
    }
    values.update(overrides)
    return Title(**values)


def test_the_unique_and_the_check_are_named_by_the_convention() -> None:
    table = Base.metadata.tables[TABLE]
    uniques = {constraint.name for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
    checks = {constraint.name for constraint in table.constraints if isinstance(constraint, CheckConstraint)}

    assert uniques == {"uq_jellyfin_item_jellyfin_id"}
    assert checks == {"ck_jellyfin_item_run_time_seconds_positive"}


def test_both_lookup_indexes_exist_under_the_names_the_queries_use() -> None:
    """`(kind, tmdb_id)` is the availability lookup; `series_jellyfin_id` is the episode join."""
    indexes: dict[str, tuple[str, ...]] = {
        str(index.name): tuple(column.name for column in index.columns)
        for index in Base.metadata.tables[TABLE].indexes
        if isinstance(index, Index)
    }

    assert indexes == {
        "ix_jellyfin_item_kind_tmdb_id": ("kind", "tmdb_id"),
        "ix_jellyfin_item_series_jellyfin_id": ("series_jellyfin_id",),
    }


def test_the_upsert_key_is_the_jellyfin_id_and_never_the_tmdb_id() -> None:
    """Two files may carry one TMDB id - that is the AMBIGUOUS case, not a constraint violation."""
    columns = Base.metadata.tables[TABLE].c

    assert columns.tmdb_id.nullable is True
    assert isinstance(columns.tmdb_id.type, Integer)
    assert isinstance(columns.jellyfin_id.type, String)
    assert columns.jellyfin_id.nullable is False


@pytest.mark.parametrize(
    "column",
    [
        "tmdb_id",
        "series_jellyfin_id",
        "parent_index_number",
        "index_number",
        "index_number_end",
        "run_time_seconds",
        "path",
        "date_last_saved",
        "removed_at",
    ],
)
def test_everything_a_server_may_omit_is_nullable(column: str) -> None:
    assert Base.metadata.tables[TABLE].c[column].nullable is True


def test_the_kind_is_a_native_enum_labelled_by_member_values() -> None:
    column_type = Base.metadata.tables[TABLE].c.kind.type

    assert isinstance(column_type, ENUM)
    assert column_type.name == "jellyfin_item_kind"
    assert list(column_type.enums) == ["movie", "series", "episode"]
    assert [member.value for member in JellyfinItemKind] == ["movie", "series", "episode"]


def test_the_index_carries_no_created_or_updated_stamp() -> None:
    """`first_seen_at` and `last_seen_at` already are this table's pair; a second one would be a lie."""
    columns = set(Base.metadata.tables[TABLE].c.keys())

    assert {"first_seen_at", "last_seen_at", "removed_at"} <= columns
    assert columns.isdisjoint({"created_at", "updated_at"})


def test_the_titles_pick_is_nullable_and_sets_null_on_delete() -> None:
    column = Base.metadata.tables["title"].c.jellyfin_item_id
    foreign_key = next(iter(column.foreign_keys))

    assert column.nullable is True
    assert foreign_key.column.table.name == TABLE
    assert foreign_key.ondelete == "SET NULL"


async def test_a_second_row_with_the_same_jellyfin_id_is_refused(db_session: AsyncSession) -> None:
    db_session.add(_item())
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_item(name="A second file claiming the same Jellyfin id"))
            await db_session.flush()


@pytest.mark.parametrize("runtime", [0, -1], ids=["zero", "negative"])
async def test_a_zero_or_negative_runtime_is_refused(db_session: AsyncSession, runtime: int) -> None:
    """The column's CHECK. Zero is the one a real body produces - the DTO admits `ge=0` - and the sync
    stores `None` for it rather than a value the database would refuse mid-scan; negative is the shape a
    floor-divided negative tick count would make, and it is refused rather than rounded into a plausible
    zero."""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_item(run_time_seconds=runtime))
            await db_session.flush()


async def test_a_removed_item_keeps_the_titles_pick(db_session: AsyncSession) -> None:
    item = _item()
    db_session.add(item)
    await db_session.flush()
    title = _a_title(jellyfin_item_id=item.id)
    db_session.add(title)
    await db_session.flush()

    # The soft delete a vanished file gets. The pick is the owner's and must survive it.
    item.removed_at = utcnow()
    await db_session.flush()

    # Read back from Postgres, not off the instance the test is holding: the identity map would report
    # the value this test assigned however the database had answered.
    stored = (await db_session.execute(select(Title.jellyfin_item_id).where(Title.id == title.id))).scalar_one()
    assert stored == item.id


async def test_a_purged_item_nulls_the_pick_rather_than_raising(db_session: AsyncSession) -> None:
    """A hand purge is the only way here - the sync never deletes - and it must not take the title with it."""
    item = _item(jellyfin_id=ANOTHER_JELLYFIN_ID)
    db_session.add(item)
    await db_session.flush()
    title = _a_title(jellyfin_item_id=item.id)
    db_session.add(title)
    await db_session.flush()

    await db_session.execute(delete(JellyfinItem).where(JellyfinItem.id == item.id))

    pick = (await db_session.execute(select(Title.jellyfin_item_id).where(Title.id == title.id))).scalar_one()
    assert pick is None


async def test_a_file_with_no_provider_id_is_a_first_class_row(db_session: AsyncSession) -> None:
    """An unmatched file is indexed with `tmdb_id` NULL; it is never matched by name instead."""
    db_session.add(_item(jellyfin_id="2c3d4e5f60718293a4b5c6d7e8f90123", name="Spider-Man", tmdb_id=None))
    await db_session.flush()

    stored = (await db_session.execute(select(JellyfinItem).where(JellyfinItem.name == "Spider-Man"))).scalar_one()
    assert stored.tmdb_id is None
    assert isinstance(stored.id, uuid.UUID)
