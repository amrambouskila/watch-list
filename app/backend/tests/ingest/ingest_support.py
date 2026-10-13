"""The recorded One Piece harness the ingest suites share: transports, factories, and a SQL tap.

Moved here whole from `test_episode_orders.py` when a second suite needed it (T24). Nothing about it
changed in the move: the same recorded bodies, the same routes, the same `httpx.MockTransport`, so the
figures T20's tests pin still come from exactly the numbers they came from before.

It exists because two suites need the same seeded title. Copying a provider harness to avoid a shared
module would put the recorded slice's shape in two places, and the second copy is always the one that
drifts (CLAUDE.md section 7). Nothing here reaches a network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Final

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provider_fixtures import (
    A_BURST_NO_TEST_EXHAUSTS,
    A_RECORDED_KEY,
    A_RECORDED_PIN,
    RECORDED_TOKEN,
    TMDB,
    TVDB,
    fixture_bytes,
    fixture_headers,
    fixture_json,
)
from statement_support import statements_against as statements_against
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.tmdb_client import TmdbClient
from tv_watchlist.clients.transport import build_provider_http
from tv_watchlist.clients.tvdb_client import TvdbClient
from tv_watchlist.constants import (
    TMDB_API_BASE_URL,
    TMDB_REQUESTS_PER_SECOND,
    TVDB_API_BASE_URL,
    TVDB_REQUESTS_PER_SECOND,
)
from tv_watchlist.data.enums import MediaType
from tv_watchlist.data.models import Title
from tv_watchlist.ingest.episode_orders import EpisodeOrderIngest
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache
from tv_watchlist.ingest.tmdb_ingest import TmdbIngest

ONE_PIECE: Final[int] = 37854
ONE_PIECE_TVDB: Final[int] = 81797
# Only seasons 0, 1 and 2 were ever recorded; every other season answers 404, which is a skip.
RECORDED_SEASONS: Final[tuple[int, ...]] = (0, 1, 2)
REGULAR_EPISODES: Final[int] = 77
SPECIALS: Final[int] = 39

# The three orderings a body was recorded for, and the pages of each. TheTVDB's own aired ordering was
# captured as one page of 1241; the other two as two pages each.
THEIR_AIRED: Final[str] = "official"
THEIR_ABSOLUTE: Final[str] = "absolute"
THEIR_DISC: Final[str] = "dvd"
RECORDED_ORDERINGS: Final[dict[str, tuple[str, ...]]] = {
    THEIR_AIRED: (f"series_81797_episodes_{THEIR_AIRED}_eng_page0",),
    THEIR_ABSOLUTE: tuple(f"series_81797_episodes_{THEIR_ABSOLUTE}_eng_page{page}" for page in (0, 1)),
    THEIR_DISC: tuple(f"series_81797_episodes_{THEIR_DISC}_eng_page{page}" for page in (0, 1)),
}
UNKNOWN_BODY: Final[str] = "series_81797_episodes_unknown_type"
A_TYPE_THE_APP_HAS_NEVER_SEEN: Final[str] = "fanedit"


# -- the recorded bodies, read page by page ---------------------------------------------------------


def recorded_page_episodes(stem: str) -> list[dict[str, object]]:
    """One recorded TheTVDB page's episode array."""
    data = fixture_json(TVDB, stem)["data"]
    assert isinstance(data, dict)
    episodes = data["episodes"]
    assert isinstance(episodes, list)
    return episodes


def recorded_episodes(season_number: int) -> list[dict[str, object]]:
    episodes = fixture_json(TMDB, f"tv_37854_season_{season_number}")["episodes"]
    assert isinstance(episodes, list)
    return episodes


# -- the recorded provider transports ---------------------------------------------------------------


class TmdbRoutes:
    """One series' recorded TMDB bodies by path; anything unrecorded answers 404, which is a skip."""

    def __init__(self) -> None:
        self._routes = {f"/3/tv/{ONE_PIECE}": "tv_37854", f"/3/tv/{ONE_PIECE}/external_ids": "tv_37854_external_ids"}
        self._routes |= {f"/3/tv/{ONE_PIECE}/season/{n}": f"tv_37854_season_{n}" for n in RECORDED_SEASONS}
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        name = self._routes.get(request.url.path)
        if name is None:
            return httpx.Response(404, json={"status_code": 34, "status_message": "resource not found"})
        return httpx.Response(200, content=fixture_bytes(TMDB, name), headers=fixture_headers(TMDB, name))


class TvdbRoutes:
    """Recorded TheTVDB bodies by path and page, with the walk terminated at the last page on disk.

    A season type with no recorded pages answers exactly what the service answers for one it does not
    offer: HTTP 200 and an empty `episodes` array. That is *unknown*, and proving the ingest treats it
    as unknown is most of the point of this file.
    """

    def __init__(
        self,
        *,
        orderings: Mapping[str, tuple[str, ...]] | None = None,
        season_types: Sequence[str] | None = None,
        episode_status: int = 200,
        overstate_by: int = 0,
    ) -> None:
        self._orderings = dict(RECORDED_ORDERINGS if orderings is None else orderings)
        self._season_types = season_types
        self._episode_status = episode_status
        self._overstate_by = overstate_by
        self.requested: list[str] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requested.append(str(request.url))
        path = request.url.path
        if path.endswith("/login"):
            return httpx.Response(200, content=fixture_bytes(TVDB, "login"))
        if path.endswith("/seasons/types"):
            return self._types()
        match = re.fullmatch(r"/v4/series/(\d+)/episodes/([^/]+)/eng", path)
        if match is None:
            return httpx.Response(404, json={"status": "failure", "message": "not found"})
        return self._page(match.group(2), int(request.url.params.get("page", "0")))

    def _types(self) -> httpx.Response:
        if self._season_types is None:
            return httpx.Response(200, content=fixture_bytes(TVDB, "seasons_types"))
        data = [
            {"id": index, "type": name, "name": name, "alternateName": None}
            for index, name in enumerate(self._season_types, start=1)
        ]
        return httpx.Response(200, content=json.dumps({"status": "success", "data": data}).encode())

    def _page(self, season_type: str, page: int) -> httpx.Response:
        if self._episode_status != 200:
            return httpx.Response(self._episode_status, json={"status": "failure", "message": "upstream said no"})
        pages = self._orderings.get(season_type, ())
        if page >= len(pages):
            # The recorded 200-with-nothing: TheTVDB's answer for an ordering it does not hold.
            return httpx.Response(200, content=fixture_bytes(TVDB, UNKNOWN_BODY))
        body = fixture_json(TVDB, pages[page])
        links = body["links"]
        assert isinstance(links, dict)
        # The recorded `next` points at the page after this one; it is kept only while that page is on
        # disk, so a walk ends where the recording ends rather than looping on a repeated answer. And
        # `total_items` is restated as what this responder actually serves, because a slice of a
        # recording that still claimed the whole ordering's count would be a short walk - which the
        # ingest refuses, correctly, and which is proved by its own test rather than by every test.
        terminated = {
            **links,
            "next": links["next"] if page + 1 < len(pages) else None,
            "total_items": self._served(pages) + self._overstate_by,
        }
        return httpx.Response(200, content=json.dumps({**body, "links": terminated}).encode())

    def _served(self, pages: Sequence[str]) -> int:
        """How many episodes this responder holds for one ordering, across every page it will serve."""
        return sum(len(recorded_page_episodes(stem)) for stem in pages)


def tmdb_ingest_for(session: AsyncSession) -> TmdbIngest:
    routes = TmdbRoutes()
    http = build_provider_http(TMDB_API_BASE_URL, headers={"Accept": "application/json"}, transport=routes.transport)
    client = TmdbClient(
        SecretStr(RECORDED_TOKEN),
        http=http,
        bucket=TokenBucket(TMDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=PostgresResponseCache(session),
    )
    return TmdbIngest(session, client)


def tvdb_client_over(routes: TvdbRoutes, session: AsyncSession, *, configured: bool = True) -> TvdbClient:
    http = build_provider_http(TVDB_API_BASE_URL, headers={"Accept": "application/json"}, transport=routes.transport)
    return TvdbClient(
        SecretStr(A_RECORDED_KEY) if configured else None,
        SecretStr(A_RECORDED_PIN) if configured else None,
        http=http,
        bucket=TokenBucket(TVDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=PostgresResponseCache(session),
    )


async def seeded_one_piece(session: AsyncSession) -> Title:
    """The recorded TMDB slice in Postgres: 24 seasons, and the episodes of the three that answered."""
    await tmdb_ingest_for(session).ingest_tv(ONE_PIECE)
    await session.flush()
    title = await session.scalar(select(Title).where(Title.media_type == MediaType.TV, Title.tmdb_id == ONE_PIECE))
    assert title is not None
    return title


def order_ingest(
    session: AsyncSession,
    *,
    orderings: Mapping[str, tuple[str, ...]] | None = None,
    season_types: Sequence[str] | None = None,
    episode_status: int = 200,
    configured: bool = True,
    overstate_by: int = 0,
) -> tuple[EpisodeOrderIngest, TvdbRoutes]:
    routes = TvdbRoutes(
        orderings=orderings,
        season_types=season_types,
        episode_status=episode_status,
        overstate_by=overstate_by,
    )
    return EpisodeOrderIngest(session, tvdb_client_over(routes, session, configured=configured)), routes
