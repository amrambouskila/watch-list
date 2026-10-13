"""`services.entries` against a real Postgres: the page, the view, the posters, and the eager-load proof.

Skipped, never mocked, when no Postgres is listening (CLAUDE.md section 16.4). The two tests that need no
database - the relationship audit and the refusal that costs no query - run everywhere.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from library_choice import a_category
from provider_fixtures import A_JELLYFIN_BASE_URL, JELLYFIN, fixture_text_response, jellyfin_client_for
from statement_support import counted_statements
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import (
    ArtworkKind,
    EntityKind,
    ExternalSource,
    MediaType,
    ResolutionState,
    UnitKind,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
)
from tv_watchlist.data.models import (
    Artwork,
    Category,
    CuratedEntry,
    CuratedEntryItem,
    Episode,
    Season,
    Title,
    WatchEvent,
)
from tv_watchlist.models.curated_entry_read import CuratedEntryRead
from tv_watchlist.services import entries as entries_service
from tv_watchlist.workbook.errors import CategoryNotFoundError

ONE_PIECE_TMDB_ID: Final[int] = 37854
PROVIDER_IDS: Final[Iterator[int]] = count(900_000)
EARLIER: Final[datetime] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
LATER: Final[datetime] = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
A_POSTER_PATH: Final[str] = "tmdb/poster.jpg"
A_PIXEL: Final[bytes] = b"not really a jpeg, and nothing here decodes it"
# The page, the selectin load of its titles, the watch-state view, the poster query, and R82's lookup of
# the workbook id behind each entry. The poster query is issued whenever the page names a title:
# `_posters_for` short-circuits on an empty set of ids, not on an empty result, so "nothing is cached"
# costs a statement that comes back empty, not no statement (services/entries.py `_posters_for`). Every
# one of the five is per PAGE rather than per row, which is what the assertion below is really about.
STATEMENTS_PER_PAGE: Final[int] = 5
LIBRARY_STATEMENTS_PER_PAGE: Final[int] = 2
# The workbook id R82 puts on the wire, for the rows that never reach a database.
A_CATEGORY_SLUG: Final[str] = "one-piece"


async def _category(session: AsyncSession, slug: str) -> Category:
    category = Category(slug=slug, file_name=f"{slug}.xlsx", sheet_title="Order", accent="#1F2937")
    session.add(category)
    await session.flush()
    return category


async def _title(session: AsyncSession, *, tmdb_id: int = ONE_PIECE_TMDB_ID) -> Title:
    title = Title(media_type=MediaType.TV, name="One Piece", match_key="one-piece", tmdb_id=tmdb_id)
    session.add(title)
    await session.flush()
    return title


async def _episodes(session: AsyncSession, title: Title, how_many: int) -> list[Episode]:
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
        for number in range(1, how_many + 1)
    ]
    session.add_all(made)
    await session.flush()
    return made


async def _entry(
    session: AsyncSession,
    category: Category,
    position: int,
    *,
    title: Title | None = None,
    cells: dict[str, str] | None = None,
    removed: bool = False,
) -> CuratedEntry:
    entry = CuratedEntry(
        category_id=category.id,
        position=position,
        sheet_row=position + 1,
        title_id=title.id if title is not None else None,
        unit_kind=UnitKind.EPISODES if title is not None else UnitKind.UNKNOWN,
        order_type="absolute" if title is not None else None,
        resolution_state=ResolutionState.CONFIRMED if title is not None else ResolutionState.UNRESOLVED,
        raw_cells=cells if cells is not None else {"order": str(position), "title": f"Row {position}"},
        raw_title=f"Row {position}",
        removed_at=LATER if removed else None,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _items(session: AsyncSession, entry: CuratedEntry, episodes: Sequence[Episode]) -> None:
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


async def _event(
    session: AsyncSession,
    category: Category,
    kind: WatchEventKind,
    occurred_at: datetime,
    *,
    episode: Episode | None = None,
    entry: CuratedEntry | None = None,
) -> None:
    session.add(
        WatchEvent(
            occurred_at=occurred_at,
            subject_kind=WatchSubjectKind.EPISODE if episode is not None else WatchSubjectKind.CURATED_ENTRY,
            kind=kind,
            source=WatchEventSource.PLAYER if episode is not None else WatchEventSource.UI,
            episode_id=episode.id if episode is not None else None,
            curated_entry_id=entry.id if entry is not None else None,
            category_id=category.id,
        )
    )
    await session.flush()


async def _poster(session: AsyncSession, title: Title, local_path: str | None) -> Artwork:
    artwork = Artwork(
        entity_kind=EntityKind.TITLE,
        kind=ArtworkKind.POSTER,
        source=ExternalSource.TMDB,
        remote_path=f"/{uuid.uuid4().hex}.jpg",
        local_path=local_path,
        is_primary=True,
        title_id=title.id,
    )
    session.add(artwork)
    await session.flush()
    return artwork


def test_only_one_relationship_can_ever_cross_the_boundary() -> None:
    """The static half of the eager-load proof: `_page` loads `title`, and `title` is all the model reads."""
    relationships = set(inspect(CuratedEntry).relationships.keys())

    assert relationships == {"category", "title", "items"}
    assert relationships & set(CuratedEntryRead.model_fields) == {"title"}


async def test_an_unknown_category_is_refused_before_any_query(settings: Settings) -> None:
    """The 404 is the library's, so it costs no database round trip - and needs no database at all.

    The session is unbound: executing anything against it raises, so "no query" is proven by the refusal
    arriving as a `CategoryNotFoundError` rather than as SQLAlchemy complaining about the bind.
    """
    with pytest.raises(CategoryNotFoundError):
        await entries_service.list_entries(AsyncSession(), settings, "no-workbook-answers-to-this")


async def test_a_never_ingested_category_is_an_empty_list(db_session: AsyncSession, settings: Settings) -> None:
    assert await entries_service.list_entries(db_session, settings, a_category().category_id) == []


async def test_the_page_is_the_sheet_order_and_skips_removed_rows(db_session: AsyncSession, settings: Settings) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    for position in (1, 2, 3, 4):
        await _entry(db_session, category, position, removed=position == 3)

    page = await entries_service.list_entries(db_session, settings, slug)

    assert [read.position for read in page] == [1, 2, 4]
    assert [read.sheet_row for read in page] == [2, 3, 5]


async def test_raw_cells_round_trips_into_cells(db_session: AsyncSession, settings: Settings) -> None:
    facts = a_category()
    grid = {"order": "1", "title": "Arlong Park", "when-to-watch": "after E30", "watched": "Watched"}
    category = await _category(db_session, facts.category_id)
    await _entry(db_session, category, 1, cells=grid)

    page = await entries_service.list_entries(db_session, settings, facts.category_id)

    assert page[0].cells == grid


async def test_limit_and_offset_page_in_position_order(db_session: AsyncSession, settings: Settings) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    for position in range(1, 6):
        await _entry(db_session, category, position)

    page = await entries_service.list_entries(db_session, settings, slug, limit=2, offset=2)

    assert [read.position for read in page] == [3, 4]


async def test_a_resolved_title_crosses_the_boundary_eagerly_loaded(
    db_session: AsyncSession, settings: Settings
) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    await _entry(db_session, category, 1, title=title)
    db_session.expunge_all()

    page = await entries_service.list_entries(db_session, settings, slug)

    assert page[0].title is not None
    assert page[0].title.tmdb_id == ONE_PIECE_TMDB_ID
    assert page[0].title.poster_url is None


async def test_an_unloaded_title_raises_rather_than_lazy_loading(db_session: AsyncSession, settings: Settings) -> None:
    """What `lazy="raise_on_sql"` buys: the miss is loud here, not a MissingGreenlet inside FastAPI."""
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    seeded = await _entry(db_session, category, 1, title=title)
    db_session.expunge_all()

    loaded = (await db_session.execute(select(CuratedEntry).where(CuratedEntry.id == seeded.id))).scalar_one()

    assert "title" in inspect(loaded).unloaded
    with pytest.raises(InvalidRequestError):
        entries_service._read(loaded, A_CATEGORY_SLUG, entries_service.UNSET_PROGRESS, {})


async def test_progress_comes_from_the_view_not_the_request(db_session: AsyncSession, settings: Settings) -> None:
    """Two completions and a skip over a three-episode span is a completed entry (CLAUDE.md 11, rule 12)."""
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    episodes = await _episodes(db_session, title, 3)
    entry = await _entry(db_session, category, 1, title=title)
    await _items(db_session, entry, episodes)
    await _event(db_session, category, WatchEventKind.COMPLETED, EARLIER, episode=episodes[0])
    await _event(db_session, category, WatchEventKind.COMPLETED, EARLIER, episode=episodes[1])
    await _event(db_session, category, WatchEventKind.SKIPPED, EARLIER, episode=episodes[2])

    page = await entries_service.list_entries(db_session, settings, slug)

    assert page[0].progress.kind is WatchEventKind.COMPLETED
    assert page[0].progress.episode_total == 3
    assert page[0].progress.episode_completed == 2
    assert page[0].progress.episode_skipped == 1
    assert page[0].progress.as_of == EARLIER


async def test_a_later_entry_level_event_wins_over_the_episode_rollup(
    db_session: AsyncSession, settings: Settings
) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    episodes = await _episodes(db_session, title, 2)
    entry = await _entry(db_session, category, 1, title=title)
    await _items(db_session, entry, episodes)
    await _event(db_session, category, WatchEventKind.COMPLETED, EARLIER, episode=episodes[0])
    await _event(db_session, category, WatchEventKind.SKIPPED, LATER, entry=entry)

    page = await entries_service.list_entries(db_session, settings, slug)

    # The coarse fact sits on top; the episode history is untouched underneath it.
    assert page[0].progress.kind is WatchEventKind.SKIPPED
    assert page[0].progress.episode_completed == 1


async def test_an_entry_with_no_events_reports_an_unset_progress(db_session: AsyncSession, settings: Settings) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    await _entry(db_session, category, 1)

    page = await entries_service.list_entries(db_session, settings, slug)

    assert page[0].progress == entries_service.UNSET_PROGRESS


async def test_a_cached_poster_becomes_a_stamped_heroes_url(
    db_session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    await _entry(db_session, category, 1, title=title)
    await _poster(db_session, title, A_POSTER_PATH)
    cached = settings.heroes_dir / A_POSTER_PATH
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(A_PIXEL)
    db_session.expunge_all()

    page = await entries_service.list_entries(db_session, settings, slug)

    assert page[0].title is not None
    assert page[0].title.poster_url == f"/heroes/{A_POSTER_PATH}?v={cached.stat().st_mtime_ns}"


@pytest.mark.parametrize("local_path", [None, A_POSTER_PATH], ids=["never-cached", "file-since-deleted"])
async def test_a_poster_with_no_bytes_on_disk_is_no_url_at_all(
    db_session: AsyncSession, settings: Settings, local_path: str | None
) -> None:
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    await _entry(db_session, category, 1, title=title)
    await _poster(db_session, title, local_path)
    db_session.expunge_all()

    page = await entries_service.list_entries(db_session, settings, slug)

    assert page[0].title is not None
    assert page[0].title.poster_url is None


@pytest.mark.parametrize("configured", [False, True])
async def test_the_page_costs_the_same_statements_whatever_its_size(
    db_session: AsyncSession, engine: AsyncEngine, settings: Settings, configured: bool
) -> None:
    """Progress and posters are fetched once for the page. One query per entry would be the N+1."""
    slug = a_category().category_id
    category = await _category(db_session, slug)
    title = await _title(db_session)
    for position in range(1, 21):
        await _entry(db_session, category, position, title=title)
    await _poster(db_session, title, None)
    db_session.expunge_all()

    # Expunged before each: a page whose rows are already in the identity map needs no selectin query,
    # and the count under test is what a fresh request costs.
    jellyfin, _ = jellyfin_client_for(
        fixture_text_response(JELLYFIN, "health"), base_url=A_JELLYFIN_BASE_URL if configured else None
    )
    try:
        with counted_statements(engine) as one:
            await entries_service.list_entries(db_session, settings, slug, limit=2, jellyfin=jellyfin)
        db_session.expunge_all()
        with counted_statements(engine) as twenty:
            await entries_service.list_entries(db_session, settings, slug, limit=20, jellyfin=jellyfin)
    finally:
        await jellyfin.aclose()

    assert len(one) == len(twenty)
    assert len(twenty) == STATEMENTS_PER_PAGE + (LIBRARY_STATEMENTS_PER_PAGE if configured else 0)


# --- The parts that need no database ----------------------------------------------------------------
# A transient ORM instance can carry an unloaded relationship without SQL being possible, so the shape
# of the wire row - the alias, the Decimal, the poster - is checkable here rather than only in CI.


def _transient_title() -> Title:
    title = Title(media_type=MediaType.TV, name="One Piece", match_key="one-piece", tmdb_id=ONE_PIECE_TMDB_ID)
    title.id = uuid.uuid4()
    return title


def _transient_entry() -> CuratedEntry:
    entry = CuratedEntry(
        position=1,
        sheet_row=2,
        unit_kind=UnitKind.EPISODES,
        order_type="absolute",
        order_label="",
        span_start=1,
        span_end=18,
        resolution_state=ResolutionState.CONFIRMED,
        resolution_confidence=Decimal("0.94"),
        # Set for the same reason `order_label` above is: this row is never flushed, so a column whose
        # default the database would have applied is still `None` on a transient instance, and the wire
        # shape declares both as `str`.
        resolution_note="",
        raw_cells={"order": "1", "title": "One Piece"},
        raw_title="One Piece",
        raw_unit="E1-18",
        raw_release="1999",
    )
    entry.id = uuid.uuid4()
    return entry


def test_the_wire_row_carries_the_cells_the_alias_names_and_a_plain_float_confidence() -> None:
    read = entries_service._read(_transient_entry(), A_CATEGORY_SLUG, entries_service.UNSET_PROGRESS, {})

    assert read.cells == {"order": "1", "title": "One Piece"}
    assert read.category_slug == A_CATEGORY_SLUG
    # Numeric(3, 2) arrives as a Decimal and leaves as the float the contract declares.
    assert read.resolution_confidence == pytest.approx(0.94)
    assert read.title is None


def test_a_titles_poster_url_is_attached_after_validation_not_read_off_a_column() -> None:
    entry, title = _transient_entry(), _transient_title()
    entry.title = title
    stamped = f"/heroes/{A_POSTER_PATH}?v=7"

    read = entries_service._read(entry, A_CATEGORY_SLUG, entries_service.UNSET_PROGRESS, {title.id: stamped})

    assert read.title is not None
    assert read.title.poster_url == stamped


def test_a_poster_path_that_leaves_the_heroes_directory_is_refused(tmp_path: Path) -> None:
    """The same resolve-and-confine check the hero download makes (CLAUDE.md section 10.3, B5/B11)."""
    heroes = tmp_path / "heroes"
    (heroes / "tmdb").mkdir(parents=True)
    outside = tmp_path / "elsewhere.jpg"
    outside.write_bytes(A_PIXEL)
    title_id = uuid.uuid4()

    assert entries_service._poster_urls(heroes, {title_id: "../elsewhere.jpg"}) == {}


def test_a_poster_row_pointing_at_nothing_servable_is_no_url_at_all(tmp_path: Path) -> None:
    """Gone, or never a file: a URL for either is a card that paints a 404."""
    heroes = tmp_path / "heroes"
    (heroes / "tmdb").mkdir(parents=True)
    (heroes / "a-directory").mkdir()

    assert entries_service._poster_urls(heroes, {uuid.uuid4(): A_POSTER_PATH}) == {}
    assert entries_service._poster_urls(heroes, {uuid.uuid4(): "a-directory"}) == {}


def test_a_poster_url_carries_the_files_own_stamp(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes"
    cached = heroes / A_POSTER_PATH
    cached.parent.mkdir(parents=True)
    cached.write_bytes(A_PIXEL)
    title_id = uuid.uuid4()

    urls = entries_service._poster_urls(heroes, {title_id: A_POSTER_PATH})

    assert urls == {title_id: f"/heroes/{A_POSTER_PATH}?v={cached.stat().st_mtime_ns}"}
