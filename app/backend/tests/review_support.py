"""Seeding for the resolution-review tests: categories, entries, and a title with one stored numbering.

Shared by the service tests and the route tests, which assert the same state machine from two sides.
Nothing here mocks the database - every function writes real rows into the test Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import count
from typing import Final

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from provider_fixtures import RECORDED_TOKEN, RecordingResponder
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import ExternalSource, MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, Episode, EpisodeOrder, Season, Title
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.services.catalog import Catalog

AN_ACCENT: Final[str] = "#1F2937"
ABSOLUTE: Final[str] = "absolute"
AIRED: Final[str] = "aired"
ONE_PIECE_TMDB_ID: Final[int] = 37854
# Enough of One Piece's absolute numbering to cover the E19-53 span the curated sheet really carries.
ONE_PIECE_EPISODES: Final[int] = 60

# `episode.tmdb_episode_id` is unique across the whole table, so seeded episodes draw from one counter
# rather than from a per-title base that a second title would collide with.
_TMDB_EPISODE_IDS = count(900_000_001)


async def seeded_category(session: AsyncSession, slug: str) -> Category:
    """One workbook's projection row. The library on disk is never consulted by the review queue."""
    category = Category(
        slug=slug,
        file_name=f"{slug}.xlsx",
        sheet_title=slug,
        accent=AN_ACCENT,
        workbook_mtime=1.0,
    )
    session.add(category)
    await session.flush()
    return category


def _cells(title: str, **optional: str) -> dict[str, str]:
    """The verbatim row as the reader keys it: every column the sheet has, blank ones included.

    Every workbook heads a title column, so its key is always here even when the cell is empty; the other
    three are only present when the test asked for them, because four of the nineteen workbooks head one
    or more of Unit, Release and Type not at all and a key those sheets never mint would be a fiction.
    """
    return {"title": title} | {key: value for key, value in optional.items() if value}


async def seeded_entry(
    session: AsyncSession,
    category: Category,
    *,
    position: int,
    state: ResolutionState = ResolutionState.UNRESOLVED,
    confidence: Decimal | None = None,
    unit_kind: UnitKind = UnitKind.UNKNOWN,
    raw_title: str = "",
    raw_unit: str = "",
    raw_release: str = "",
    raw_type: str = "",
    title: Title | None = None,
    note: str = "",
) -> CuratedEntry:
    """One curated row, in whatever state the test needs it to start in.

    `raw_cells` is keyed the way the reader keys it - by the slug a header derives, never by the header -
    because the retry reads the Type cell back out of it (`curated_columns.raw_type_cell`).
    """
    entry = CuratedEntry(
        category_id=category.id,
        position=position,
        sheet_row=position + 1,
        unit_kind=unit_kind,
        resolution_state=state,
        resolution_confidence=confidence,
        resolution_note=note,
        raw_cells=_cells(title=raw_title, unit=raw_unit, release=raw_release, type=raw_type),
        raw_title=raw_title,
        raw_unit=raw_unit,
        raw_release=raw_release,
        title_id=None if title is None else title.id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def seeded_title(session: AsyncSession, *, name: str, tmdb_id: int | None = None) -> Title:
    """A title row that no provider call produced - the hand-entered case is first class (R2)."""
    title = Title(media_type=MediaType.TV, tmdb_id=tmdb_id, name=name, match_key=name.lower())
    session.add(title)
    await session.flush()
    return title


async def seeded_episodes(session: AsyncSession, title: Title, *, episodes: int = ONE_PIECE_EPISODES) -> list[Episode]:
    """`episodes` episodes in one season of this title, numbered 1..n."""
    season = Season(title_id=title.id, season_number=1, name="Season 1", episode_count=episodes)
    session.add(season)
    await session.flush()
    rows = [
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=1,
            episode_number=number,
            tmdb_episode_id=next(_TMDB_EPISODE_IDS),
            name=f"Episode {number}",
        )
        for number in range(1, episodes + 1)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def seeded_numbering(
    session: AsyncSession, title: Title, episodes: Sequence[Episode], *, order_type: str = ABSOLUTE
) -> None:
    """Rank those episodes 1..n under `order_type`, with the canonical empty label.

    A second numbering over the same episodes reuses the very same rows: `uq(episode_id, order_type,
    label)` is what tells the two orderings apart, not a second copy of the episodes.
    """
    session.add_all(
        EpisodeOrder(
            title_id=title.id,
            episode_id=episode.id,
            order_type=order_type,
            label="",
            sequence=sequence,
            order_season_number=1,
            order_episode_number=sequence,
            source=ExternalSource.TMDB,
        )
        for sequence, episode in enumerate(episodes, start=1)
    )
    await session.flush()


def tmdb_runtime(
    settings: Settings,
    catalog: Catalog,
    engine: AsyncEngine,
    *responses: httpx.Response,
    token: str | None = RECORDED_TOKEN,
) -> IngestRuntime:
    """An `IngestRuntime` whose TMDB leg answers from recorded bodies. No test here reaches a network."""
    return recording_tmdb_runtime(settings, catalog, engine, *responses, token=token)[0]


def recording_tmdb_runtime(
    settings: Settings,
    catalog: Catalog,
    engine: AsyncEngine,
    *responses: httpx.Response,
    token: str | None = RECORDED_TOKEN,
) -> tuple[IngestRuntime, RecordingResponder]:
    """The same runtime, with the responder handed back beside it.

    A refusal that is meant to cost nothing has to be proved to have cost nothing, and the only place
    that is visible is the transport: `responder.requests == []` says no provider call was made, where
    an unchanged row only says none of them landed.

    `token=None` is the unconfigured provider: the client refuses before a request is built, which is
    the state a correct-with-a-tmdb-id has to be refused in rather than silently skipped.
    """
    responder = RecordingResponder(*responses) if responses else RecordingResponder(httpx.Response(404, json={}))
    configured = settings.model_copy(update={"tmdb_read_access_token": None if token is None else SecretStr(token)})
    runtime = IngestRuntime.from_settings(
        configured, catalog, async_sessionmaker(engine), transport=responder.transport
    )
    return runtime, responder
