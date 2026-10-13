"""`media_import`: named CHECK constraints, the partial-unique defence behind `duplicate_skipped`,
three `ON DELETE SET NULL` parents, and the `MediaImportRead` conversion that must not lazy-load.

The shape assertions are offline - a naming convention and a nullability are properties of the metadata.
The ones that matter most are not: a CHECK only Postgres itself can be asked to enforce, a partial unique
index that IS the whole of `duplicate_skipped`'s defence, and a foreign key whose action only a real
foreign key can be asked to perform.

Ruling 100 (fix round 1): `identified_has_title` used to require `title_id NOT NULL` for any status past
`found`/`unidentified`/`failed`. `title_id`'s FK is `ON DELETE SET NULL`, and Postgres re-validates every
row-level CHECK after an FK's SET NULL action fires - so that CHECK made a title purge behind a `moved` or
`identified` row **refuse** rather than null cleanly, inverting the deletion policy that title metadata
cascades freely (CLAUDE.md 5.13). The renamed `identified_records_how` ties the same idea to `identified_by`
instead - a plain enum column no parent delete can touch - so the invariant survives a title purge, and the
purge itself now nulls cleanly for every status (`test_purging_a_title_nulls_the_pointer_for_every_status`
is the assertion that would have failed under the old schema and passes under this one). The "and has a
title" half of the old predicate moves to the write path - see
`test_the_database_no_longer_requires_a_title_for_an_identified_row` below for where that lands today, and
its docstring for which task inherits the real enforcement.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Final

import pytest
from episode_join_support import a_film, a_series_file, a_show
from pydantic import ValidationError
from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint, delete, inspect, select
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tv_watchlist.clock import utcnow
from tv_watchlist.data.base import Base
from tv_watchlist.data.enums import MediaImportIdentifiedBy, MediaImportSource, MediaImportStatus
from tv_watchlist.data.models import Episode, JellyfinItem, MediaImport, Title
from tv_watchlist.models.media_import_read import MediaImportRead

TABLE: Final[str] = "media_import"
A_SOURCE_PATH: Final[str] = "/staging/one.piece.s01e01.mkv"
A_SIZE_BYTES: Final[int] = 1_500_000_000
A_SHA256: Final[str] = "a" * 64
ANOTHER_SHA256: Final[str] = "b" * 64
IRON_MAN_TMDB_ID: Final[int] = 1726


def _row(**overrides: object) -> MediaImport:
    values: dict[str, object] = {
        "source": MediaImportSource.STAGING_FOLDER,
        "source_path": A_SOURCE_PATH,
        "original_name": "One.Piece.S01E01.mkv",
        "size_bytes": A_SIZE_BYTES,
        "status": MediaImportStatus.FOUND,
    }
    values.update(overrides)
    return MediaImport(**values)


def _self_superseded() -> dict[str, object]:
    """`id` is fixed ahead of insertion so `superseded_by_id` can name the row's own id."""
    fixed = uuid.uuid4()
    return {"id": fixed, "superseded_by_id": fixed, "superseded_at": utcnow()}


# R76: `stopped_has_error` gets two cases - a `failed` row and an `unidentified` row, each with
# `error IS NULL` - the rest one case each: nine named constraints, ten cases in all. `moved_has_path` and
# `hashed_has_digest` carry `identified_by` alongside them, because `identified_records_how` requires one
# for any status but found/unidentified/failed - without it the row would fail on the WRONG constraint
# first. None of these need a `title_id` any more (Ruling 100): that half left the database entirely.
CHECK_VIOLATIONS: Final[dict[str, Callable[[], dict[str, object]]]] = {
    "size_positive": lambda: {"size_bytes": 0},
    "sha256_shape": lambda: {"file_sha256": "too-short"},
    "confidence_range": lambda: {"identification_confidence": 1.5},
    "identified_records_how": lambda: {"status": MediaImportStatus.IDENTIFIED, "identified_by": None},
    "moved_has_path": lambda: {
        "status": MediaImportStatus.MOVED,
        "identified_by": MediaImportIdentifiedBy.FILENAME,
        "file_path": None,
    },
    "hashed_has_digest": lambda: {
        "status": MediaImportStatus.HASHED,
        "identified_by": MediaImportIdentifiedBy.FILENAME,
        "file_path": "one.mkv",
        "file_sha256": None,
    },
    "stopped_has_error_failed": lambda: {"status": MediaImportStatus.FAILED, "error": None},
    "stopped_has_error_unidentified": lambda: {"status": MediaImportStatus.UNIDENTIFIED, "error": None},
    "superseded_pair": lambda: {"superseded_at": utcnow(), "superseded_by_id": None},
    "not_self_superseded": _self_superseded,
}

# What each status needs, beyond the base row, to satisfy every OTHER named check - so the comprehensive
# purge test below (and the digest tests) exercise a status without tripping something unrelated.
_VALID_EXTRAS_FOR_STATUS: Final[dict[MediaImportStatus, dict[str, object]]] = {
    MediaImportStatus.FOUND: {},
    MediaImportStatus.IDENTIFIED: {"identified_by": MediaImportIdentifiedBy.FILENAME},
    MediaImportStatus.MOVED: {"identified_by": MediaImportIdentifiedBy.FILENAME, "file_path": "found.mkv"},
    MediaImportStatus.HASHED: {
        "identified_by": MediaImportIdentifiedBy.FILENAME,
        "file_path": "found.mkv",
        "file_sha256": A_SHA256,
    },
    MediaImportStatus.REFRESHED: {
        "identified_by": MediaImportIdentifiedBy.FILENAME,
        "file_path": "found.mkv",
        "file_sha256": A_SHA256,
    },
    MediaImportStatus.FAILED: {"error": "the move failed"},
    MediaImportStatus.DUPLICATE_SKIPPED: {"identified_by": MediaImportIdentifiedBy.OWNER_PICK},
    MediaImportStatus.UNIDENTIFIED: {"error": "no candidate scored high enough"},
}


def test_the_checks_are_named_by_the_convention() -> None:
    checks = {
        constraint.name
        for constraint in Base.metadata.tables[TABLE].constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert checks == {
        f"ck_{TABLE}_{name}"
        for name in (
            "size_positive",
            "sha256_shape",
            "confidence_range",
            "identified_records_how",
            "moved_has_path",
            "hashed_has_digest",
            "stopped_has_error",
            "superseded_pair",
            "not_self_superseded",
        )
    }


def test_the_table_carries_no_full_table_unique_constraint() -> None:
    """The only uniqueness here is the partial index below - live rows only, not the whole table."""
    uniques = {
        constraint for constraint in Base.metadata.tables[TABLE].constraints if isinstance(constraint, UniqueConstraint)
    }
    assert uniques == set()


def test_every_index_exists_under_the_name_the_queries_use() -> None:
    """The three hand-named indexes, plus the three plain btrees `mapped_column(..., index=True)` mints."""
    indexes = {str(index.name) for index in Base.metadata.tables[TABLE].indexes}
    assert indexes == {
        "ix_media_import_live_sha256",
        "ix_media_import_status_found_at",
        "ix_media_import_source_path",
        "ix_media_import_title_id",
        "ix_media_import_episode_id",
        "ix_media_import_jellyfin_item_id",
    }


def test_the_live_sha256_index_is_partial_and_unique() -> None:
    index = next(index for index in Base.metadata.tables[TABLE].indexes if index.name == "ix_media_import_live_sha256")
    where = index.dialect_options["postgresql"]["where"]

    assert index.unique is True
    assert str(where) == (
        "file_sha256 IS NOT NULL AND superseded_at IS NULL AND status IN ('moved', 'hashed', 'refreshed')"
    )


def test_the_status_found_at_index_covers_the_paged_list() -> None:
    index = next(
        index for index in Base.metadata.tables[TABLE].indexes if index.name == "ix_media_import_status_found_at"
    )
    assert tuple(column.name for column in index.columns) == ("status", "found_at")


@pytest.mark.parametrize(
    ("column", "target", "ondelete"),
    [
        ("title_id", "title", "SET NULL"),
        ("episode_id", "episode", "SET NULL"),
        ("jellyfin_item_id", "jellyfin_item", "SET NULL"),
        ("superseded_by_id", TABLE, "RESTRICT"),
    ],
)
def test_every_foreign_key_carries_the_action_a_provenance_row_needs(column: str, target: str, ondelete: str) -> None:
    foreign_key = next(iter(Base.metadata.tables[TABLE].c[column].foreign_keys))
    assert foreign_key.column.table.name == target
    assert foreign_key.ondelete == ondelete
    assert Base.metadata.tables[TABLE].c[column].nullable is True


def test_size_bytes_is_a_big_integer_not_a_plain_integer() -> None:
    """A 4K remux or a Blu-ray rip routinely exceeds 2 GiB, which is where a plain int4 column overflows."""
    assert isinstance(Base.metadata.tables[TABLE].c.size_bytes.type, BigInteger)


def test_status_has_no_server_default() -> None:
    """A row is always created by the scan with an explicit status, never one Postgres invents for it."""
    assert Base.metadata.tables[TABLE].c.status.server_default is None


@pytest.mark.parametrize(
    ("column", "name", "labels"),
    [
        ("source", "media_import_source", ("staging_folder", "qbittorrent_completed", "manual")),
        ("identified_by", "media_import_identified_by", ("filename", "owner_pick")),
        (
            "status",
            "media_import_status",
            ("found", "identified", "moved", "hashed", "refreshed", "failed", "duplicate_skipped", "unidentified"),
        ),
    ],
)
def test_every_enum_column_is_native_and_labelled_by_member_values(
    column: str, name: str, labels: tuple[str, ...]
) -> None:
    column_type = Base.metadata.tables[TABLE].c[column].type
    assert isinstance(column_type, ENUM)
    assert column_type.name == name
    assert column_type.create_type is False
    assert tuple(column_type.enums) == labels


@pytest.mark.parametrize("name", sorted(CHECK_VIOLATIONS), ids=sorted(CHECK_VIOLATIONS))
async def test_a_named_check_rejects_its_own_violation(db_session: AsyncSession, name: str) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_row(**CHECK_VIOLATIONS[name]()))
            await db_session.flush()


async def test_a_second_live_row_with_the_same_digest_is_refused(db_session: AsyncSession) -> None:
    db_session.add(
        _row(
            identified_by=MediaImportIdentifiedBy.FILENAME,
            file_path="first.mkv",
            file_sha256=A_SHA256,
            status=MediaImportStatus.MOVED,
        )
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                _row(
                    identified_by=MediaImportIdentifiedBy.FILENAME,
                    source_path="/staging/second.mkv",
                    file_path="second.mkv",
                    file_sha256=A_SHA256,
                    status=MediaImportStatus.MOVED,
                )
            )
            await db_session.flush()


async def test_the_same_digest_is_accepted_once_the_first_row_is_superseded(db_session: AsyncSession) -> None:
    first = _row(
        identified_by=MediaImportIdentifiedBy.FILENAME,
        file_path="first.mkv",
        file_sha256=A_SHA256,
        status=MediaImportStatus.MOVED,
    )
    db_session.add(first)
    await db_session.flush()

    second = _row(
        identified_by=MediaImportIdentifiedBy.FILENAME,
        source_path="/staging/second.mkv",
        file_path="second.mkv",
        file_sha256=ANOTHER_SHA256,
        status=MediaImportStatus.MOVED,
    )
    db_session.add(second)
    await db_session.flush()

    first.superseded_at = utcnow()
    first.superseded_by_id = second.id
    await db_session.flush()
    second.file_sha256 = A_SHA256
    # A superseded row keeps its digest without blocking the row that replaced it.
    await db_session.flush()


@pytest.mark.parametrize("status", list(MediaImportStatus), ids=lambda status: status.value)
async def test_purging_a_title_nulls_the_pointer_for_every_status(
    db_session: AsyncSession, status: MediaImportStatus
) -> None:
    """Ruling 100, the assertion the fix is for: this failed for every status but found/unidentified/failed
    under the old `identified_has_title` CHECK, which tied `title_id`'s presence to `status` and therefore
    fought the FK's own `ON DELETE SET NULL` the moment a title behind a `moved`/`identified`/... row was
    purged. `identified_records_how` ties the same idea to `identified_by` instead, which no parent delete
    can touch, so every status now nulls cleanly."""
    title = await a_film(db_session, "Iron Man", tmdb_id=IRON_MAN_TMDB_ID)
    row = _row(title_id=title.id, status=status, **_VALID_EXTRAS_FOR_STATUS[status])
    db_session.add(row)
    await db_session.flush()

    await db_session.execute(delete(Title).where(Title.id == title.id))

    # A column-only select, never `select(MediaImport)`: the identity map would keep serving this test its
    # own in-memory copy of `row`, which the FK's out-of-band SET NULL never touches.
    stored = (await db_session.execute(select(MediaImport.title_id).where(MediaImport.id == row.id))).scalar_one()
    assert stored is None


async def test_the_database_no_longer_requires_a_title_for_an_identified_row(db_session: AsyncSession) -> None:
    """Ruling 100: the old `identified_has_title` CHECK's `title_id IS NOT NULL` half is gone from the
    database entirely, moved to the write path - the service that creates/identifies a row is meant to
    refuse advancing a row past `found`/`unidentified`/`failed` without a `title_id`, but no such service
    exists yet (`services/import_identify.py`, T65, is where a row transitions `found` -> `identified` and
    where that enforcement - and its own test - belongs). This test lives here today because that is where
    it CAN live: it proves the database side of the change (permissive, so the FK's SET NULL is never
    fought) rather than the service side (not yet built). If a later change reintroduces a database-level
    title requirement, this is the test that will catch it."""
    row = _row(status=MediaImportStatus.IDENTIFIED, identified_by=MediaImportIdentifiedBy.FILENAME, title_id=None)
    db_session.add(row)
    await db_session.flush()  # must not raise

    stored = (await db_session.execute(select(MediaImport.title_id).where(MediaImport.id == row.id))).scalar_one()
    assert stored is None


async def test_a_purged_episode_nulls_the_pointer_and_keeps_the_row(db_session: AsyncSession) -> None:
    title = await a_show(db_session, "Test Show", episodes=1)
    episode = (await db_session.execute(select(Episode).where(Episode.title_id == title.id))).scalar_one()
    row = _row(episode_id=episode.id, status=MediaImportStatus.FOUND)
    db_session.add(row)
    await db_session.flush()

    await db_session.execute(delete(Episode).where(Episode.id == episode.id))

    stored = (await db_session.execute(select(MediaImport.episode_id).where(MediaImport.id == row.id))).scalar_one()
    assert stored is None


async def test_a_purged_jellyfin_item_nulls_the_pointer_and_keeps_the_row(db_session: AsyncSession) -> None:
    item = await a_series_file(
        db_session, jellyfin_id="0a1b2c3d4e5f6071829304a5b6c7d8ff", name="One Piece", tmdb_id=None
    )
    row = _row(jellyfin_item_id=item.id, status=MediaImportStatus.FOUND)
    db_session.add(row)
    await db_session.flush()

    await db_session.execute(delete(JellyfinItem).where(JellyfinItem.id == item.id))

    stored = (
        await db_session.execute(select(MediaImport.jellyfin_item_id).where(MediaImport.id == row.id))
    ).scalar_one()
    assert stored is None


async def test_media_import_read_converts_from_an_eagerly_loaded_row(db_session: AsyncSession) -> None:
    title = await a_film(db_session, "Iron Man", tmdb_id=IRON_MAN_TMDB_ID)
    row = _row(title_id=title.id, status=MediaImportStatus.IDENTIFIED, identified_by=MediaImportIdentifiedBy.FILENAME)
    db_session.add(row)
    await db_session.flush()
    db_session.expunge_all()

    loaded = (
        await db_session.execute(
            select(MediaImport).where(MediaImport.id == row.id).options(selectinload(MediaImport.title))
        )
    ).scalar_one()

    read = MediaImportRead.model_validate(loaded)
    assert read.title_id == title.id
    assert read.title_name == "Iron Man"


async def test_media_import_read_raises_rather_than_lazy_loading_the_title(db_session: AsyncSession) -> None:
    """What `lazy="raise_on_sql"` buys: the miss is loud here, not a `MissingGreenlet` inside FastAPI.

    Pydantic's `from_attributes` conversion wraps whatever the `title_name` property raises into its own
    `ValidationError` (`type=get_attribute_error`) rather than letting `InvalidRequestError` propagate
    bare, so the assertion is on the wrapped message, not the exception type - the guard still fired.
    """
    title = await a_film(db_session, "Iron Man", tmdb_id=IRON_MAN_TMDB_ID)
    row = _row(title_id=title.id, status=MediaImportStatus.IDENTIFIED, identified_by=MediaImportIdentifiedBy.FILENAME)
    db_session.add(row)
    await db_session.flush()
    db_session.expunge_all()

    loaded = (await db_session.execute(select(MediaImport).where(MediaImport.id == row.id))).scalar_one()

    assert "title" in inspect(loaded).unloaded
    with pytest.raises(ValidationError) as error:
        MediaImportRead.model_validate(loaded)
    assert "raise_on_sql" in str(error.value)
