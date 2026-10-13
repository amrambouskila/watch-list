"""A stand-in Jellyfin that answers by URL, plus the fixture library every sync test walks.

At the tests root because two suites drive the same server - the service's own tests and the route's -
and a second copy of a transport is the copy that drifts (CLAUDE.md section 7).

**By URL, not by call order.** Sequential canned answers made every assertion depend on the order
`sync_library` happens to make its calls in, which is exactly what R89 changed when an incremental pass
gained a second walk between the scan and the per-series calls. Dispatching on the request is what lets
the order be *asserted* rather than relied on.

Nothing here opens a socket. The bodies are the hand-authored ones under `tests/fixtures/jellyfin/`,
shaped from 12.1's OpenAPI document - that directory's README says why, and what the T54 gate settles.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Final

import httpx

from provider_fixtures import (
    A_JELLYFIN_BASE_URL,
    JELLYFIN,
    RecordingResponder,
    fixture_json,
    jellyfin_client_for,
)
from tv_watchlist.clients.jellyfin_client import JellyfinClient
from tv_watchlist.constants import JELLYFIN_EPISODE_TYPE, JELLYFIN_MOVIE_TYPE, JELLYFIN_SERIES_TYPE

ITEMS_PATH: Final[str] = "/Items"
EPISODES_SEGMENT: Final[str] = "Episodes"
TYPES_PARAM: Final[str] = "includeItemTypes"
CURSOR_PARAM: Final[str] = "minDateLastSaved"
TMDB_FILTER_PARAM: Final[str] = "hasTmdbId"
SCAN_TYPES: Final[str] = f"{JELLYFIN_MOVIE_TYPE},{JELLYFIN_SERIES_TYPE}"

# The fixture library: three movies, three series, and One Piece's three episode files.
ONE_PIECE_SERIES_ID: Final[str] = "5c1d3f2a4b6e47d8a9f0c1b2d3e4f5a6"
EVERY_SERIES_ID: Final[tuple[str, ...]] = (
    ONE_PIECE_SERIES_ID,
    "7e2a9b4c1d3f48a6b5c7d9e0f1a2b3c4",
    "9f3b1c5d7e2a48c6b4d8e0f2a1c3b5d7",
)
MOVIES: Final[int] = 3
SERIES: Final[int] = 3
EPISODES: Final[int] = 3
LIBRARY_ROWS: Final[int] = MOVIES + SERIES + EPISODES


def items_of(name: str) -> list[dict[str, object]]:
    """One fixture's `Items` array, so several bodies can be spliced into the pages a walk sees."""
    items = fixture_json(JELLYFIN, name)["Items"]
    if not isinstance(items, list):
        raise TypeError(f"{name}.json has no Items array")
    # Copied, because a test that renames a file must not rename it for every later test in the process.
    return [json.loads(json.dumps(item)) for item in items if isinstance(item, dict)]


def page(items: Sequence[dict[str, object]]) -> httpx.Response:
    """A complete page: `TotalRecordCount` equals what is handed back, so a walk stops after one call."""
    return httpx.Response(200, json={"Items": list(items), "TotalRecordCount": len(items), "StartIndex": 0})


def library_items(*, without: str | None = None) -> list[dict[str, object]]:
    """Every movie and series the scan returns, optionally missing one file that has since vanished."""
    rows = items_of("items_movies_page1") + items_of("items_series_page1") + items_of("items_series_page2")
    return [row for row in rows if row.get("Id") != without]


class JellyfinLibrary(RecordingResponder):
    """Answers `/Items`, the episode delta and `/Shows/{id}/Episodes` from three separate collections."""

    def __init__(
        self,
        *,
        scan: Sequence[dict[str, object]] = (),
        episodes: Mapping[str, Sequence[dict[str, object]]] | None = None,
        changed_episodes: Sequence[dict[str, object]] = (),
    ) -> None:
        self._scan = list(scan)
        self._episodes = {series: list(items) for series, items in (episodes or {}).items()}
        self._changed_episodes = list(changed_episodes)
        # One unused response, because the base class builds its transport over `_handle` - which this
        # class replaces outright - and still wants a non-empty list to have been handed to it.
        super().__init__(page([]))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith(f"/{EPISODES_SEGMENT}"):
            return page(self._episodes.get(request.url.path.split("/")[-2], []))
        if request.url.params.get(TYPES_PARAM) == JELLYFIN_EPISODE_TYPE:
            return page(self._changed_episodes)
        return page(self._scan)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def asked_for_the_episode_delta(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.params.get(TYPES_PARAM) == JELLYFIN_EPISODE_TYPE]


def fixture_library(
    *, without: str | None = None, changed_episodes: Sequence[dict[str, object]] = ()
) -> JellyfinLibrary:
    """The whole fixture library, as one server that answers every call the sync makes."""
    return JellyfinLibrary(
        scan=library_items(without=without),
        episodes={ONE_PIECE_SERIES_ID: items_of("shows_episodes_one_piece")},
        changed_episodes=changed_episodes,
    )


def client_for(responder: JellyfinLibrary, *, base_url: str | None = A_JELLYFIN_BASE_URL) -> JellyfinClient:
    """A `JellyfinClient` pointed at that server. `base_url=None` is the disabled shape, not a broken one."""
    client, _ = jellyfin_client_for(base_url=base_url, responder=responder)
    return client
