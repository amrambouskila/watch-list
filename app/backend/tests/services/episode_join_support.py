"""Builders the two episode-join suites share: a show with its numbering, its files, and a row to hang them on.

One copy, because `test_episode_lookup.py` and `test_episode_match.py` both want a title whose ordering is
known to the digit, and a second copy is always the one that drifts (CLAUDE.md section 7).

Nothing here opens a socket. The Jellyfin rows are built with the shapes the hand-authored bodies under
`tests/fixtures/jellyfin/` carry - and the multi-episode file is read straight out of one of them - so what
this seeds is what a sync would have written, without a sync to write it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from itertools import count
from typing import Final

from ingest_support import order_ingest, seeded_one_piece
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provider_fixtures import JELLYFIN, fixture_json
from tv_watchlist.constants import SPECIALS_ORDER_LABEL
from tv_watchlist.data.enums import ExternalSource, JellyfinItemKind, MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, Episode, EpisodeOrder, JellyfinItem, Season, Title
from tv_watchlist.ingest.episode_orders import AIRED_ORDER_TYPE, NO_LABEL, SPECIALS_ORDER_TYPE

#: Clear of the recorded One Piece slice's own `tmdb_episode_id` values, which are real TMDB numbers.
_TMDB_EPISODE_IDS: Final[count[int]] = count(9_000_001)
#: The 28 hex digits every hand-written file id in these suites starts with; the last four are the episode.
_FILE_ID_STEM: Final[str] = "0f1e2d3c4b5a69788796a5b4c3d2"
SPECIALS_SEASON: Final[int] = 0
A_FIRST_SEASON: Final[int] = 1
#: The hand-authored episode bodies T49's suite replays, borrowed here for their `IndexNumberEnd` file.
ONE_PIECE_EPISODES_FIXTURE: Final[str] = "shows_episodes_one_piece"


def file_id(number: int) -> str:
    """A hand-written 32-hex Jellyfin item id, the shape `tests/fixtures/jellyfin/` uses."""
    return f"{_FILE_ID_STEM}{number:04x}"


def fixture_episodes() -> list[dict[str, object]]:
    """One fixture's `Items` array: the three One Piece files, one of which covers two episodes."""
    items = fixture_json(JELLYFIN, ONE_PIECE_EPISODES_FIXTURE)["Items"]
    if not isinstance(items, list):
        raise TypeError(f"{ONE_PIECE_EPISODES_FIXTURE}.json has no Items array")
    return [item for item in items if isinstance(item, dict)]


def fixture_series_id() -> str:
    """The Jellyfin series id those files hang under, read rather than restated."""
    series_id = fixture_episodes()[0]["SeriesId"]
    if not isinstance(series_id, str):
        raise TypeError(f"{ONE_PIECE_EPISODES_FIXTURE}.json carries no SeriesId")
    return series_id


async def files_from_fixture(session: AsyncSession, *, series_jellyfin_id: str) -> list[JellyfinItem]:
    """The fixture's episode bodies as `jellyfin_item` rows - the fields the join reads, nothing else."""
    rows = [
        JellyfinItem(
            jellyfin_id=str(item["Id"]),
            kind=JellyfinItemKind.EPISODE,
            name=str(item["Name"]),
            series_jellyfin_id=series_jellyfin_id,
            parent_index_number=_number(item.get("ParentIndexNumber")),
            index_number=_number(item.get("IndexNumber")),
            index_number_end=_number(item.get("IndexNumberEnd")),
            path=str(item["Path"]),
        )
        for item in fixture_episodes()
    ]
    session.add_all(rows)
    await session.flush()
    return rows


def _number(value: object) -> int | None:
    return value if isinstance(value, int) else None


async def one_piece_with_its_orderings(session: AsyncSession) -> Title:
    """The recorded slice, plus every numbering T20 writes for it: the aired walk, the specials bucket
    and each ordering TheTVDB offered. Shared, because both suites need a real provider's own ranks."""
    title = await seeded_one_piece(session)
    ingest, _ = order_ingest(session)
    await ingest.rank_aired(title)
    await ingest.ingest_tvdb_orders(title)
    await session.flush()
    return title


async def a_category(session: AsyncSession, slug: str = "a-category") -> Category:
    category = Category(slug=slug, file_name=f"{slug}.xlsx", sheet_title="Watch Order", accent="#1F2937")
    session.add(category)
    await session.flush()
    return category


async def a_show(
    session: AsyncSession,
    name: str,
    *,
    episodes: int,
    season_number: int = A_FIRST_SEASON,
    specials: int = 0,
    tmdb_id: int | None = None,
) -> Title:
    """A tv title whose aired walk is `(season_number, 1..episodes)`, with an optional specials bucket."""
    title = Title(media_type=MediaType.TV, tmdb_id=tmdb_id, name=name, match_key=name.casefold())
    session.add(title)
    await session.flush()
    await _numbered(session, title, season_number, episodes, AIRED_ORDER_TYPE, NO_LABEL)
    if specials:
        await _numbered(session, title, SPECIALS_SEASON, specials, SPECIALS_ORDER_TYPE, SPECIALS_ORDER_LABEL)
    return title


async def a_film(session: AsyncSession, name: str, *, tmdb_id: int | None = None) -> Title:
    title = Title(media_type=MediaType.MOVIE, tmdb_id=tmdb_id, name=name, match_key=name.casefold())
    session.add(title)
    await session.flush()
    return title


async def _numbered(
    session: AsyncSession, title: Title, season_number: int, episodes: int, order_type: str, label: str
) -> None:
    """One season's episodes and the numbering they sit in, exactly as T20's own walks write them."""
    season = Season(title_id=title.id, season_number=season_number)
    session.add(season)
    await session.flush()
    rows = [
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=season_number,
            episode_number=number,
            tmdb_episode_id=next(_TMDB_EPISODE_IDS),
        )
        for number in range(1, episodes + 1)
    ]
    session.add_all(rows)
    await session.flush()
    session.add_all(
        [
            EpisodeOrder(
                title_id=title.id,
                episode_id=episode.id,
                order_type=order_type,
                label=label,
                sequence=number,
                order_season_number=season_number,
                order_episode_number=number,
                source=ExternalSource.TMDB,
            )
            for number, episode in enumerate(rows, start=1)
        ]
    )
    await session.flush()


async def an_entry(
    session: AsyncSession,
    category: Category,
    *,
    title_id: uuid.UUID | None,
    unit_kind: UnitKind,
    order_type: str | None = None,
    order_label: str = NO_LABEL,
    span_start: int | None = None,
    span_end: int | None = None,
    season_number: int | None = None,
    position: int = 1,
) -> CuratedEntry:
    """One entry as the reconciler leaves it, ready for `rebuild_items` to expand."""
    entry = CuratedEntry(
        category_id=category.id,
        position=position,
        title_id=title_id,
        unit_kind=unit_kind,
        order_type=order_type,
        order_label=order_label,
        span_start=span_start,
        span_end=span_end,
        season_number=season_number,
        resolution_state=ResolutionState.AUTO,
        raw_cells={},
    )
    session.add(entry)
    await session.flush()
    return entry


async def a_series_file(session: AsyncSession, *, jellyfin_id: str, name: str, tmdb_id: int | None) -> JellyfinItem:
    """One series row of the library index. `tmdb_id` None is a file Jellyfin's own scan never matched."""
    row = JellyfinItem(jellyfin_id=jellyfin_id, kind=JellyfinItemKind.SERIES, name=name, tmdb_id=tmdb_id)
    session.add(row)
    await session.flush()
    return row


async def an_episode_file(
    session: AsyncSession,
    *,
    series_jellyfin_id: str,
    season: int,
    number: int,
    number_end: int | None = None,
    jellyfin_id: str | None = None,
    removed_at: datetime | None = None,
) -> JellyfinItem:
    """One episode file as Jellyfin reports it: its own numbers, verbatim, whatever the naming produced."""
    row = JellyfinItem(
        jellyfin_id=file_id(number) if jellyfin_id is None else jellyfin_id,
        kind=JellyfinItemKind.EPISODE,
        name=f"Episode {number}",
        series_jellyfin_id=series_jellyfin_id,
        parent_index_number=season,
        index_number=number,
        index_number_end=number_end,
        path=f"/media/shows/Season {season:02d}/S{season:02d}E{number:02d}.mkv",
        removed_at=removed_at,
    )
    session.add(row)
    await session.flush()
    return row


async def a_second_numbering(
    session: AsyncSession,
    title: Title,
    *,
    order_type: str,
    label: str = NO_LABEL,
    season_number: int,
    first_number: int,
) -> None:
    """A provider ordering over the same episodes, printing a DIFFERENT `(season, episode)` pair.

    The shape a stray `order_type` on a season row would join under if anything let it: the ranks are the
    same episodes in the same order, but the pair the UI prints - and the pair a file is named for - is
    somewhere else entirely. A join that addressed this numbering would answer for the wrong file, or for
    none at all.
    """
    episodes = list(
        await session.scalars(
            select(Episode)
            .where(Episode.title_id == title.id, Episode.season_number != SPECIALS_SEASON)
            .order_by(Episode.season_number, Episode.episode_number)
        )
    )
    session.add_all(
        [
            EpisodeOrder(
                title_id=title.id,
                episode_id=episode.id,
                order_type=order_type,
                label=label,
                sequence=rank,
                order_season_number=season_number,
                order_episode_number=first_number + rank - 1,
                source=ExternalSource.TVDB,
            )
            for rank, episode in enumerate(episodes, start=1)
        ]
    )
    await session.flush()
