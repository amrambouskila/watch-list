"""Revision 0001 against a real Postgres: the objects it creates, and what the two views actually derive.

Skipped, never mocked, when no Postgres is listening (CLAUDE.md section 16.4).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from itertools import count
from typing import Final

import pytest
from sqlalchemy import Row, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.data.enums import MediaType, WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, Episode, Season, Title, WatchEvent

EXPECTED_TABLES: Final[frozenset[str]] = frozenset(
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
EXPECTED_VIEWS: Final[frozenset[str]] = frozenset({"episode_watch_state", "curated_entry_watch_state"})
EXPECTED_ENUMS: Final[frozenset[str]] = frozenset(
    {
        "media_type",
        "unit_kind",
        "resolution_state",
        "entity_kind",
        "external_source",
        "artwork_kind",
        "watch_event_kind",
        "watch_event_source",
        "watch_subject_kind",
        "sync_resource_type",
    }
)

ENTRY_STATE: Final[str] = (
    "SELECT kind, episode_total, episode_completed, episode_skipped, episode_started "
    "FROM curated_entry_watch_state WHERE curated_entry_id = :id"
)
# Fixed instants rather than now(): precedence is about which event is later, and a test that says so
# should not also depend on how fast it runs.
EARLIER: Final[datetime] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LATER: Final[datetime] = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
# Every test rolls back, so these only have to be unique inside one transaction.
PROVIDER_IDS: Final[Iterator[int]] = count(1)
# Postgres 23001, the ERRCODE the revision's trigger raises with.
RESTRICT_VIOLATION: Final[str] = "23001"


async def _names(engine: AsyncEngine, sql: str) -> set[str]:
    async with engine.connect() as connection:
        return {row[0] for row in await connection.execute(text(sql))}


async def _category(session: AsyncSession) -> Category:
    category = Category(slug=f"probe-{uuid.uuid4().hex}", file_name="Probe.xlsx", sheet_title="Probe", accent="#1F2937")
    session.add(category)
    await session.flush()
    return category


async def _series(session: AsyncSession, episodes: int) -> list[Episode]:
    title = Title(media_type=MediaType.TV, name="Probe Series", match_key="probe-series", tmdb_id=next(PROVIDER_IDS))
    session.add(title)
    await session.flush()
    season = Season(title_id=title.id, season_number=1)
    session.add(season)
    await session.flush()
    made = [
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=1,
            episode_number=number,
            tmdb_episode_id=next(PROVIDER_IDS),
        )
        for number in range(1, episodes + 1)
    ]
    session.add_all(made)
    await session.flush()
    return made


async def _movie(session: AsyncSession) -> Title:
    title = Title(media_type=MediaType.MOVIE, name="Probe Film", match_key="probe-film", tmdb_id=next(PROVIDER_IDS))
    session.add(title)
    await session.flush()
    return title


async def _entry_over(session: AsyncSession, category: Category, units: Sequence[Episode | Title]) -> CuratedEntry:
    """One entry and one curated_entry_item per playable unit - an episode, or a movie's single slot."""
    entry = CuratedEntry(category_id=category.id, position=1, raw_cells={"Title": "Probe"})
    session.add(entry)
    await session.flush()
    session.add_all(
        CuratedEntryItem(
            category_id=category.id,
            curated_entry_id=entry.id,
            episode_id=unit.id if isinstance(unit, Episode) else None,
            movie_title_id=unit.id if isinstance(unit, Title) else None,
            position_in_entry=slot,
            absolute_position=slot,
        )
        for slot, unit in enumerate(units, start=1)
    )
    await session.flush()
    return entry


async def _record(
    session: AsyncSession,
    category: Category,
    kind: WatchEventKind,
    occurred_at: datetime,
    *,
    episode: Episode | None = None,
    movie: Title | None = None,
    entry: CuratedEntry | None = None,
) -> None:
    """One watch_event against exactly one subject - the `one_subject` CHECK allows nothing else."""
    if episode is not None:
        subject_kind = WatchSubjectKind.EPISODE
    elif movie is not None:
        subject_kind = WatchSubjectKind.TITLE
    else:
        subject_kind = WatchSubjectKind.CURATED_ENTRY
    session.add(
        WatchEvent(
            occurred_at=occurred_at,
            subject_kind=subject_kind,
            kind=kind,
            # A unit-level fact comes from the player; an entry-level one is typed into the app.
            source=WatchEventSource.UI if entry is not None else WatchEventSource.PLAYER,
            episode_id=episode.id if episode is not None else None,
            title_id=movie.id if movie is not None else None,
            curated_entry_id=entry.id if entry is not None else None,
            category_id=category.id,
        )
    )
    await session.flush()


async def _state(session: AsyncSession, entry: CuratedEntry) -> Row[tuple[str, int, int, int, int]]:
    return (await session.execute(text(ENTRY_STATE), {"id": entry.id})).one()


async def test_every_table_exists(engine: AsyncEngine) -> None:
    tables = await _names(engine, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    assert EXPECTED_TABLES <= tables


async def test_both_views_exist(engine: AsyncEngine) -> None:
    assert EXPECTED_VIEWS <= await _names(engine, "SELECT viewname FROM pg_views WHERE schemaname = 'public'")


async def test_every_enum_type_exists_once(engine: AsyncEngine) -> None:
    assert EXPECTED_ENUMS <= await _names(engine, "SELECT typname FROM pg_type WHERE typtype = 'e'")


async def test_pg_trgm_and_the_trigram_index_exist(engine: AsyncEngine) -> None:
    assert "pg_trgm" in await _names(engine, "SELECT extname FROM pg_extension")
    assert "ix_title_name_trgm" in await _names(engine, "SELECT indexname FROM pg_indexes WHERE tablename = 'title'")


async def test_the_append_only_trigger_is_installed(engine: AsyncEngine) -> None:
    assert "watch_event_no_mutation" in await _names(engine, "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")


@pytest.mark.parametrize(
    ("index_name", "table"),
    [
        ("ix_curated_entry_needs_review", "curated_entry"),
        ("ix_sync_state_due", "sync_state"),
        ("ix_watch_event_episode_latest", "watch_event"),
        ("ix_watch_event_entry_latest", "watch_event"),
        ("ix_artwork_primary_title", "artwork"),
    ],
)
async def test_the_partial_indexes_exist(engine: AsyncEngine, index_name: str, table: str) -> None:
    async with engine.connect() as connection:
        definitions = [
            row[0]
            for row in await connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :name AND tablename = :table"),
                {"name": index_name, "table": table},
            )
        ]
    assert definitions and all(" WHERE " in definition for definition in definitions)


async def test_an_entry_with_no_units_reports_unset_until_something_is_recorded(db_session: AsyncSession) -> None:
    """An unresolved entry - no title, no items - still renders and still takes an entry-level event."""
    category = await _category(db_session)
    entry = await _entry_over(db_session, category, [])
    assert (await _state(db_session, entry))[:3] == ("unset", 0, 0)

    await _record(db_session, category, WatchEventKind.COMPLETED, EARLIER, entry=entry)
    assert (await _state(db_session, entry))[:3] == ("completed", 0, 0)


async def test_an_entry_event_later_than_every_unit_event_takes_precedence(db_session: AsyncSession) -> None:
    """A coarse `Watched?` typed into Excel sits on top of episode history without erasing it."""
    category = await _category(db_session)
    episodes = await _series(db_session, 1)
    entry = await _entry_over(db_session, category, episodes)
    await _record(db_session, category, WatchEventKind.COMPLETED, EARLIER, episode=episodes[0])
    await _record(db_session, category, WatchEventKind.SKIPPED, LATER, entry=entry)

    kind, total, completed, _skipped, _started = await _state(db_session, entry)
    assert kind == "skipped"
    # The roll-up underneath is untouched, which is what lets the next unit event take over.
    assert (total, completed) == (1, 1)


async def test_a_unit_event_later_than_the_entry_event_takes_the_wheel_back(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    episodes = await _series(db_session, 1)
    entry = await _entry_over(db_session, category, episodes)
    await _record(db_session, category, WatchEventKind.SKIPPED, EARLIER, entry=entry)
    await _record(db_session, category, WatchEventKind.COMPLETED, LATER, episode=episodes[0])

    kind, total, completed, _skipped, _started = await _state(db_session, entry)
    assert (kind, total, completed) == ("completed", 1, 1)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (WatchEventKind.SKIPPED, WatchEventKind.SKIPPED, "skipped"),
        (WatchEventKind.COMPLETED, WatchEventKind.SKIPPED, "completed"),
        (WatchEventKind.COMPLETED, None, "progressed"),
        (WatchEventKind.STARTED, None, "progressed"),
        (None, None, "unset"),
    ],
    ids=["all skipped", "completed plus skipped", "one of two completed", "one of two started", "nothing recorded"],
)
async def test_the_roll_up_branch_each_mix_of_unit_events_lands_in(
    db_session: AsyncSession, first: WatchEventKind | None, second: WatchEventKind | None, expected: str
) -> None:
    """completed + skipped = total counts as completed - the same semantics as WatchCounts.trackable."""
    category = await _category(db_session)
    episodes = await _series(db_session, 2)
    entry = await _entry_over(db_session, category, episodes)
    for episode, kind in zip(episodes, (first, second), strict=True):
        if kind is not None:
            await _record(db_session, category, kind, EARLIER, episode=episode)

    kind_now, total, *_ = await _state(db_session, entry)
    assert (kind_now, total) == (expected, 2)


async def test_a_movie_slot_counts_through_a_title_level_event(db_session: AsyncSession) -> None:
    """A film has no episode row, so its progress reaches the roll-up through title_states or not at all."""
    category = await _category(db_session)
    movie = await _movie(db_session)
    entry = await _entry_over(db_session, category, [movie])
    await _record(db_session, category, WatchEventKind.COMPLETED, EARLIER, movie=movie)

    kind, total, completed, _skipped, _started = await _state(db_session, entry)
    assert (kind, total, completed) == ("completed", 1, 1)


async def test_the_append_only_refusal_carries_the_restrict_violation_sqlstate(db_session: AsyncSession) -> None:
    """Complements test_watch_event_append_only.py, which proves the refusal happens at all.

    This pins the SQLSTATE the revision's `USING ERRCODE = 'restrict_violation'` sets. Dropping that clause
    would still raise - as a bare P0001 - and every message-matching test would still pass.
    """
    category = await _category(db_session)
    entry = await _entry_over(db_session, category, await _series(db_session, 1))
    await _record(db_session, category, WatchEventKind.COMPLETED, EARLIER, entry=entry)

    with pytest.raises(DBAPIError) as refusal:
        await db_session.execute(
            update(WatchEvent).where(WatchEvent.curated_entry_id == entry.id).values(note="rewritten")
        )
    assert refusal.value.orig is not None
    assert refusal.value.orig.sqlstate == RESTRICT_VIOLATION
