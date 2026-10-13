"""Appending one watch fact, and the progress the views derive from it.

The database is real and skips loudly without one: the premise under test is an append-only log read
back through two `DISTINCT ON` views, and a mocked database would prove only that the mock agrees with
itself (CLAUDE.md section 16.4). Nothing here reaches a network, and nothing here opens a workbook -
the mirror's own half is tested in tests/services/test_watch_mirror_database.py.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from database_support import JoiningSessionFactory
from statement_support import counted_statements
from tv_watchlist.constants import UNWATCHED, WATCHED
from tv_watchlist.data.enums import (
    MediaType,
    UnitKind,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
)
from tv_watchlist.data.errors import EntryNotFoundError, WatchSubjectNotFoundError
from tv_watchlist.data.models import (
    Category,
    CuratedEntry,
    CuratedEntryItem,
    Episode,
    Season,
    Title,
    WatchEvent,
)
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.mirror_outcome import DEFERRED, WRITTEN
from tv_watchlist.services.watch_events import entry_progress, mirror_recorded_entry, record_watch_event
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.schema import watch_column
from workbook_facts import WorkbookFacts

NOW: Final[datetime] = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
AN_HOUR_AGO: Final[datetime] = datetime(2026, 9, 20, 14, 0, tzinfo=UTC)
EARLIER: Final[datetime] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LATER: Final[datetime] = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
# Every test rolls back, so these only have to be unique inside one transaction.
PROVIDER_IDS: Final[Iterator[int]] = count(1)
ONE_PIECE_TMDB_ID: Final[int] = 37854
# CLAUDE.md section 11.2, rule 9: TMDB buckets anime absolutely, so Laboon is season 2, episode 62.
LABOON_SEASON: Final[int] = 2
LABOON_EPISODE: Final[int] = 62
LABOON_KEY: Final[str] = "tv:37854:s2:e62"
FIGHT_CLUB_TMDB_ID: Final[int] = 550
AN_ACCENT: Final[str] = "#1F2937"
FIRST_SHEET_ROW: Final[int] = 2
A_POSITION: Final[int] = 42
SERVICE_LOGGER: Final[str] = "tv_watchlist.services.watch_events"


def _clock() -> datetime:
    return NOW


async def _category(session: AsyncSession, slug: str = "probe") -> Category:
    category = Category(slug=slug, file_name=f"{slug}.xlsx", sheet_title="Order", accent=AN_ACCENT)
    session.add(category)
    await session.flush()
    return category


async def _entry(
    session: AsyncSession, category: Category, *, position: int = 1, title: Title | None = None
) -> CuratedEntry:
    entry = CuratedEntry(
        category_id=category.id,
        position=position,
        sheet_row=FIRST_SHEET_ROW + position - 1,
        unit_kind=UnitKind.EPISODES,
        raw_cells={"title": "Probe"},
        raw_title="Probe",
        title_id=None if title is None else title.id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _series(session: AsyncSession, *, tmdb_id: int | None = ONE_PIECE_TMDB_ID) -> Title:
    title = Title(media_type=MediaType.TV, name="One Piece", match_key="one piece", tmdb_id=tmdb_id)
    session.add(title)
    await session.flush()
    return title


async def _film(session: AsyncSession, *, tmdb_id: int = FIGHT_CLUB_TMDB_ID) -> Title:
    title = Title(media_type=MediaType.MOVIE, name="Fight Club", match_key="fight club", tmdb_id=tmdb_id)
    session.add(title)
    await session.flush()
    return title


async def _episodes(
    session: AsyncSession, title: Title, *, season_number: int, numbers: Sequence[int]
) -> list[Episode]:
    season = Season(title_id=title.id, season_number=season_number)
    session.add(season)
    await session.flush()
    episodes = [
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=season_number,
            episode_number=number,
            tmdb_episode_id=next(PROVIDER_IDS),
        )
        for number in numbers
    ]
    session.add_all(episodes)
    await session.flush()
    return episodes


async def _queued(session: AsyncSession, entry: CuratedEntry, episodes: Sequence[Episode]) -> None:
    session.add_all(
        CuratedEntryItem(
            category_id=entry.category_id,
            curated_entry_id=entry.id,
            episode_id=episode.id,
            position_in_entry=slot,
            absolute_position=slot,
        )
        for slot, episode in enumerate(episodes, start=1)
    )
    await session.flush()


async def _queued_film(session: AsyncSession, entry: CuratedEntry, title: Title) -> None:
    """A film entry occupies exactly one slot, which is what lets Next walk through it (ADR-010)."""
    session.add(
        CuratedEntryItem(
            category_id=entry.category_id,
            curated_entry_id=entry.id,
            movie_title_id=title.id,
            position_in_entry=1,
            absolute_position=1,
        )
    )
    await session.flush()


def _body(subject_kind: WatchSubjectKind, subject_id: uuid.UUID, **overrides: Any) -> WatchEventCreate:  # noqa: ANN401  # a passthrough is as typed as what it wraps
    # Named `subject_kind`, not `kind`: an override naming the event's own kind must not collide with it.
    payload: dict[str, Any] = {
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "kind": WatchEventKind.COMPLETED,
    }
    payload.update(overrides)
    return WatchEventCreate.model_validate(payload)


async def _stored(session: AsyncSession, event_id: uuid.UUID) -> WatchEvent:
    """The row as the database holds it, read past the identity map."""
    return (await session.execute(select(WatchEvent).where(WatchEvent.id == event_id))).scalar_one()


# -- the typed FK the subject maps onto ----------------------------------------------------------------


async def test_an_episode_subject_fills_the_episode_column_and_no_other(db_session: AsyncSession) -> None:
    """`one_subject` allows exactly one; the affected entry travels on the response, not in the row."""
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=LABOON_SEASON, numbers=[LABOON_EPISODE])
    await _queued(db_session, entry, episodes)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)

    stored = await _stored(db_session, read.id)
    assert stored.episode_id == episodes[0].id
    assert stored.title_id is None
    assert stored.curated_entry_id is None
    assert stored.category_id == category.id
    assert read.curated_entry_id == entry.id


async def test_a_title_subject_fills_the_title_column(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    film = await _film(db_session)
    entry = await _entry(db_session, category, title=film)
    await _queued_film(db_session, entry, film)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.TITLE, film.id), clock=_clock)

    stored = await _stored(db_session, read.id)
    assert stored.title_id == film.id
    assert stored.episode_id is None
    assert stored.curated_entry_id is None
    assert read.curated_entry_id == entry.id


async def test_a_curated_entry_subject_fills_the_entry_column_and_carries_its_own_category(
    db_session: AsyncSession,
) -> None:
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)

    stored = await _stored(db_session, read.id)
    assert stored.curated_entry_id == entry.id
    assert stored.category_id == category.id
    assert stored.episode_id is None
    assert stored.title_id is None


@pytest.mark.parametrize(
    "kind",
    list(WatchSubjectKind),
    ids=[kind.value for kind in WatchSubjectKind],
)
async def test_a_subject_the_projection_does_not_hold_is_refused_before_anything_is_written(
    db_session: AsyncSession, kind: WatchSubjectKind
) -> None:
    """Resolved first, so an id nothing answers to is a 404 rather than an integrity error."""
    missing = uuid.uuid4()

    with pytest.raises(WatchSubjectNotFoundError, match=str(missing)):
        await record_watch_event(db_session, _body(kind, missing), clock=_clock)

    assert await db_session.scalar(select(WatchEvent.id).limit(1)) is None


async def test_a_soft_deleted_entry_takes_no_new_events(db_session: AsyncSession) -> None:
    """Retirement moves rather than deletes, and a moved row is not a subject to record against."""
    category = await _category(db_session)
    entry = await _entry(db_session, category)
    entry.removed_at = NOW
    await db_session.flush()

    with pytest.raises(WatchSubjectNotFoundError):
        await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)


# -- the tmdb key, derived server-side -----------------------------------------------------------------


async def test_an_episode_event_carries_the_episodes_own_tmdb_pointer(db_session: AsyncSession) -> None:
    """The reference value: TMDB buckets One Piece absolutely, so Laboon is s2e62, not s1e62."""
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=LABOON_SEASON, numbers=[LABOON_EPISODE])
    await _queued(db_session, entry, episodes)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)

    assert read.tmdb_key == LABOON_KEY


async def test_a_film_event_carries_the_works_own_pointer(db_session: AsyncSession) -> None:
    film = await _film(db_session)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.TITLE, film.id), clock=_clock)

    assert read.tmdb_key == f"movie:{FIGHT_CLUB_TMDB_ID}"


async def test_an_entry_event_borrows_its_titles_pointer(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category, title=title)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)

    assert read.tmdb_key == f"tv:{ONE_PIECE_TMDB_ID}"


async def test_an_unresolved_entry_records_a_fact_with_no_pointer(db_session: AsyncSession) -> None:
    """A row TMDB cannot be matched to is still a row the owner meant (CLAUDE.md section 18.2)."""
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)

    assert read.tmdb_key is None


async def test_a_title_with_no_provider_match_records_a_fact_with_no_pointer(db_session: AsyncSession) -> None:
    title = await _series(db_session, tmdb_id=None)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.TITLE, title.id), clock=_clock)

    assert read.tmdb_key is None


# -- the stamps ----------------------------------------------------------------------------------------


async def test_occurred_at_defaults_to_now_and_recorded_at_is_server_time(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)

    stamps = (
        await db_session.execute(select(WatchEvent.occurred_at, WatchEvent.recorded_at).where(WatchEvent.id == read.id))
    ).one()
    assert stamps.occurred_at == NOW
    # Server-assigned, so it is the database's clock rather than the injected one.
    assert stamps.recorded_at != NOW
    assert read.recorded_at == stamps.recorded_at


async def test_a_late_client_stamp_is_stored_as_given(db_session: AsyncSession) -> None:
    """A player or Jellyfin report can arrive an hour after the thing it describes."""
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    read = await record_watch_event(
        db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id, occurred_at=AN_HOUR_AGO), clock=_clock
    )

    assert read.occurred_at == AN_HOUR_AGO


async def test_a_naive_client_stamp_is_read_as_utc(db_session: AsyncSession) -> None:
    """The column is timestamptz; asyncpg refuses a naive datetime rather than guessing a zone."""
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    read = await record_watch_event(
        db_session,
        _body(WatchSubjectKind.CURATED_ENTRY, entry.id, occurred_at=AN_HOUR_AGO.replace(tzinfo=None)),
        clock=_clock,
    )

    assert read.occurred_at == AN_HOUR_AGO


# -- the source ----------------------------------------------------------------------------------------


async def test_the_source_is_the_ui_unless_the_caller_says_otherwise(db_session: AsyncSession) -> None:
    """Phase 3's player passes `player` through this same service; `jellyfin` is never a source."""
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    default = await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)
    player = await record_watch_event(
        db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), source=WatchEventSource.PLAYER, clock=_clock
    )

    assert default.source is WatchEventSource.UI
    assert player.source is WatchEventSource.PLAYER


# -- the derived state ---------------------------------------------------------------------------------


async def test_one_completion_of_a_span_reads_as_progressed(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1, 2, 3])
    await _queued(db_session, entry, episodes)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)

    assert read.progress is not None
    assert read.progress.kind is WatchEventKind.PROGRESSED
    assert read.progress.episode_total == len(episodes)
    assert read.progress.episode_completed == 1


async def test_completed_plus_skipped_equals_total_reads_as_completed(db_session: AsyncSession) -> None:
    """The same arithmetic `WatchCounts.trackable` uses, so the two progress readouts cannot disagree."""
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1, 2])
    await _queued(db_session, entry, episodes)

    await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)
    read = await record_watch_event(
        db_session,
        _body(WatchSubjectKind.EPISODE, episodes[1].id, kind=WatchEventKind.SKIPPED),
        clock=_clock,
    )

    assert read.progress is not None
    assert read.progress.kind is WatchEventKind.COMPLETED
    assert read.progress.episode_skipped == 1


async def test_an_entry_level_event_later_than_every_episode_event_wins(db_session: AsyncSession) -> None:
    """A coarse status sits on top of the fine-grained history without erasing it (section 11.2, rule 12)."""
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1, 2])
    await _queued(db_session, entry, episodes)
    await record_watch_event(
        db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id, occurred_at=EARLIER), clock=_clock
    )

    read = await record_watch_event(
        db_session,
        _body(WatchSubjectKind.CURATED_ENTRY, entry.id, kind=WatchEventKind.SKIPPED, occurred_at=LATER),
        clock=_clock,
    )

    assert read.progress is not None
    assert read.progress.kind is WatchEventKind.SKIPPED
    # The episode history is still underneath it, untouched.
    assert read.progress.episode_completed == 1


async def test_an_episode_no_curated_row_covers_records_a_fact_with_no_progress(db_session: AsyncSession) -> None:
    title = await _series(db_session)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1])

    read = await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)

    assert read.progress is None
    assert read.curated_entry_id is None
    assert read.category_id is None


async def test_the_body_names_which_categorys_entry_an_episode_moves(db_session: AsyncSession) -> None:
    """One playable unit can sit in several curated orders; `category_id` is how a caller picks one."""
    first = await _category(db_session, slug="first")
    second = await _category(db_session, slug="second")
    title = await _series(db_session)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1])
    in_first = await _entry(db_session, first)
    in_second = await _entry(db_session, second)
    await _queued(db_session, in_first, episodes)
    await _queued(db_session, in_second, episodes)

    read = await record_watch_event(
        db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id, category_id=second.id), clock=_clock
    )

    assert read.curated_entry_id == in_second.id
    assert read.category_id == second.id


# -- the derived read ------------------------------------------------------------------------------------


async def test_the_derived_read_answers_for_a_live_entry(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    progress = await entry_progress(db_session, entry.id, category_slug=category.slug)

    assert progress.kind is WatchEventKind.UNSET
    assert progress.episode_total == 0


async def test_the_derived_read_refuses_an_entry_of_another_category(db_session: AsyncSession) -> None:
    """The path says "this entry, of this category", so it must not answer for another one's."""
    category = await _category(db_session)
    other = await _category(db_session, slug="other")
    entry = await _entry(db_session, category)

    with pytest.raises(EntryNotFoundError, match=str(entry.id)):
        await entry_progress(db_session, entry.id, category_slug=other.slug)


@pytest.mark.parametrize("narrowed", [True, False], ids=["narrowed-by-category", "by-id-alone"])
async def test_the_derived_read_refuses_an_id_no_live_entry_answers_to(
    db_session: AsyncSession, narrowed: bool
) -> None:
    category = await _category(db_session)
    missing = uuid.uuid4()

    with pytest.raises(EntryNotFoundError, match=str(missing)):
        await entry_progress(db_session, missing, category_slug=category.slug if narrowed else None)


async def test_the_derived_read_matches_what_recording_returned(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1, 2])
    await _queued(db_session, entry, episodes)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)

    assert await entry_progress(db_session, entry.id, category_slug=category.slug) == read.progress


# -- append-only, in the service as well as in the trigger -------------------------------------------------


async def test_the_service_never_updates_or_deletes_a_watch_event(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    """The trigger (T10) is the structural guarantee; this is the service holding up its end of it."""
    category = await _category(db_session)
    title = await _series(db_session)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1, 2])
    await _queued(db_session, entry, episodes)

    with counted_statements(engine, "watch_event") as touching:
        await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)
        await record_watch_event(
            db_session,
            _body(WatchSubjectKind.EPISODE, episodes[1].id, kind=WatchEventKind.SKIPPED),
            clock=_clock,
        )

    assert touching
    assert all(statement.lstrip().upper().startswith("INSERT") for statement in touching)


async def test_a_correction_is_another_insert_and_the_later_one_wins(db_session: AsyncSession) -> None:
    """Nothing is ever rewritten: the views collapse the log at read time."""
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    await record_watch_event(
        db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id, occurred_at=EARLIER), clock=_clock
    )
    read = await record_watch_event(
        db_session,
        _body(WatchSubjectKind.CURATED_ENTRY, entry.id, kind=WatchEventKind.UNSET, occurred_at=LATER),
        clock=_clock,
    )

    assert read.progress is not None
    assert read.progress.kind is WatchEventKind.UNSET
    assert await db_session.scalar(select(WatchEvent.id).where(WatchEvent.curated_entry_id == entry.id)) is not None


async def test_the_position_a_player_reports_is_stored_as_whole_seconds(db_session: AsyncSession) -> None:
    category = await _category(db_session)
    entry = await _entry(db_session, category)

    read = await record_watch_event(
        db_session,
        _body(
            WatchSubjectKind.CURATED_ENTRY,
            entry.id,
            kind=WatchEventKind.PROGRESSED,
            position_seconds=A_POSITION,
            runtime_seconds=1440,
        ),
        source=WatchEventSource.PLAYER,
        clock=_clock,
    )

    stored = await _stored(db_session, read.id)
    assert stored.position_seconds == A_POSITION
    assert stored.runtime_seconds == 1440


async def test_an_episode_of_an_unmatched_title_records_a_fact_with_no_pointer(db_session: AsyncSession) -> None:
    """A hand-entered local title carries no provider id, and an episode of it carries no pointer either."""
    category = await _category(db_session)
    title = await _series(db_session, tmdb_id=None)
    entry = await _entry(db_session, category)
    episodes = await _episodes(db_session, title, season_number=1, numbers=[1])
    await _queued(db_session, entry, episodes)

    read = await record_watch_event(db_session, _body(WatchSubjectKind.EPISODE, episodes[0].id), clock=_clock)

    assert read.tmdb_key is None
    assert read.curated_entry_id == entry.id


# -- the scheduled mirror ------------------------------------------------------------------------------


class _ASessionWhoseCommitFails:
    """The test's own session, with the one statement most likely to fail made to fail."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401  # a passthrough is as typed as what it wraps
        return getattr(self._session, name)

    async def commit(self) -> None:
        raise OperationalError("COMMIT", None, RuntimeError("the connection went away"))


class _AFactoryWhoseCommitFails(JoiningSessionFactory):
    """The shared factory, handing back a session that cannot commit what the mirror just wrote."""

    async def __aenter__(self) -> _ASessionWhoseCommitFails:
        return _ASessionWhoseCommitFails(await super().__aenter__())


class _Mirrorable:
    """One real workbook with a category row, one entry, and the status column to project onto."""

    def __init__(self, path: Path, entry: CuratedEntry, watch_key: str, sheet_row: int) -> None:
        self.path = path
        self.entry = entry
        self.watch_key = watch_key
        self.sheet_row = sheet_row

    def cell(self) -> str:
        return {row.row: row.cells for row in read_category(self.path).rows}[self.sheet_row][self.watch_key]


async def _mirrorable(session: AsyncSession, library: Path, subject: WorkbookFacts) -> _Mirrorable:
    """A category ingested once, with a completion already recorded against its first row."""
    path = subject.copied_into(library)
    detail = read_category(path)
    column = watch_column(detail.columns)
    assert column is not None
    category = Category(
        slug=detail.id,
        file_name=detail.file_name,
        sheet_title=detail.sheet_title,
        accent=detail.accent,
        workbook_mtime=detail.mtime,
    )
    session.add(category)
    await session.flush()
    entry = CuratedEntry(
        category_id=category.id, position=1, sheet_row=detail.rows[0].row, raw_cells={"title": "Probe"}
    )
    session.add(entry)
    await session.flush()
    await record_watch_event(session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)
    return _Mirrorable(path, entry, column.key, detail.rows[0].row)


async def test_the_scheduled_mirror_writes_the_status_cell_through_a_factory_of_its_own(
    db_session: AsyncSession, catalog: Catalog, library: Path, subject: WorkbookFacts
) -> None:
    """The other half of "progress is written to both": what the owner sees when they open the file."""
    mirrorable = await _mirrorable(db_session, library, subject)

    outcome = await mirror_recorded_entry(JoiningSessionFactory(db_session), catalog, mirrorable.entry.id, clock=_clock)

    assert outcome == WRITTEN
    assert mirrorable.cell() == WATCHED
    assert mirrorable.entry.mirrored_watch_cell == WATCHED


async def test_a_workbook_the_library_no_longer_holds_defers_the_mirror_rather_than_raising(
    db_session: AsyncSession, catalog: Catalog
) -> None:
    """The expected refusal, logged quietly: the mirror is the writer that is supposed to lose."""
    category = await _category(db_session, slug="no-workbook-answers-to-this")
    category.workbook_mtime = 1.0
    entry = await _entry(db_session, category)
    await record_watch_event(db_session, _body(WatchSubjectKind.CURATED_ENTRY, entry.id), clock=_clock)

    outcome = await mirror_recorded_entry(JoiningSessionFactory(db_session), catalog, entry.id, clock=_clock)

    assert outcome == DEFERRED
    assert entry.mirrored_watch_cell == UNWATCHED


async def test_a_commit_that_fails_after_the_write_is_logged_and_deferred_not_raised(
    db_session: AsyncSession,
    catalog: Catalog,
    library: Path,
    subject: WorkbookFacts,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The commit is inside the `try` because it is the statement most likely to be the one that fails.

    The response has already been sent by the time this runs, so the only honest outcome is a logged
    deferral: the sheet carries the value, Postgres does not yet, and the next pass replays the diff.
    """
    mirrorable = await _mirrorable(db_session, library, subject)

    with caplog.at_level(logging.ERROR, logger=SERVICE_LOGGER):
        outcome = await mirror_recorded_entry(
            _AFactoryWhoseCommitFails(db_session), catalog, mirrorable.entry.id, clock=_clock
        )

    assert outcome == DEFERRED
    assert "watch_event_mirror_crashed" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)
