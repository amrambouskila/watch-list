"""`POST /api/library/sync` through the real application.

Three promises are under test and two of them are about what the route does NOT do. It never answers 500
when the media server is stopped, absent or unconfigured - a disabled feature is data, and the workbooks
have to keep opening either way (CLAUDE.md section 6.6). Nothing about Jellyfin reaches the browser
through it: not the base URL, not an item id, not the key (section 10.3, B16), asserted by reading the
whole response text because the interesting failure is a field nobody thought to look at. And two
overlapping requests do not race each other into a duplicate-key 500 (R88).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Final

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from jellyfin_library import CURSOR_PARAM, JellyfinLibrary, client_for, fixture_library
from provider_fixtures import A_JELLYFIN_BASE_URL, A_RECORDED_JELLYFIN_KEY
from tv_watchlist.api.dependencies import get_jellyfin_client
from tv_watchlist.api.errors import payload_for
from tv_watchlist.clients.jellyfin_client import JellyfinClient, build_jellyfin_http
from tv_watchlist.data.errors import JellyfinUnavailableError
from tv_watchlist.data.models import JellyfinItem
from tv_watchlist.data.session import get_session
from tv_watchlist.main import create_app

SYNC_PATH: Final[str] = "/api/library/sync"
ONE_PIECE_SERIES_ID: Final[str] = "5c1d3f2a4b6e47d8a9f0c1b2d3e4f5a6"
IRON_MAN_ID: Final[str] = "0a1b2c3d4e5f6071829304a5b6c7d8e9"
LIBRARY_ROWS: Final[int] = 9
RESULT_KEYS: Final[frozenset[str]] = frozenset({"seen", "added", "updated", "removed", "synced_at", "incremental"})
A_CURSOR: Final[datetime] = datetime(2026, 9, 20, 12, 30, tzinfo=UTC)
A_CURSOR_WITH_NO_OFFSET: Final[str] = "2026-09-20T12:30:00"
# Nothing about the media server may appear in a response body, whichever way the request ended.
NEVER_IN_A_BODY: Final[tuple[str, ...]] = (
    A_JELLYFIN_BASE_URL,
    A_RECORDED_JELLYFIN_KEY,
    ONE_PIECE_SERIES_ID,
    IRON_MAN_ID,
    "jellyfin:8096",
    "MediaBrowser",
)


def _an_unreachable_jellyfin() -> JellyfinClient:
    """Configured and simply not answering - a different path from an absent one, and the one whose
    upstream error text could have carried the `Authorization` header into the envelope."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    http = build_jellyfin_http(A_JELLYFIN_BASE_URL, transport=httpx.MockTransport(refuse))
    return JellyfinClient(A_JELLYFIN_BASE_URL, SecretStr(A_RECORDED_JELLYFIN_KEY), http=http)


def _wired(client: JellyfinClient, session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_jellyfin_client] = lambda: client
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _post(client: JellyfinClient, session: AsyncSession, **params: str) -> Response:
    async with _wired(client, session) as http:
        return await http.post(SYNC_PATH, params=params)


async def _live_sessions(engine: AsyncEngine, count: int) -> AsyncIterator[list[AsyncSession]]:
    """Real, separately-connected sessions that COMMIT, so a lock two of them contend for is a real lock.

    The rolled-back `db_session` fixture is one connection and cannot contend with itself. These write
    for real, so the rows are swept up afterwards rather than rolled back - the database is this
    process's own throwaway one, but a later test in the same process would still see what was left.
    """
    sessions = [AsyncSession(bind=engine, expire_on_commit=False, autoflush=False) for _ in range(count)]
    try:
        yield sessions
    finally:
        for session in sessions:
            await session.close()
        async with AsyncSession(bind=engine) as sweeper:
            await sweeper.execute(delete(JellyfinItem))
            await sweeper.commit()


def test_jellyfin_unavailable_error_is_registered_in_both_error_tables() -> None:
    """R72. Unregistered, it would silently become a 400 carrying `str(error)` as its whole message."""
    envelope = payload_for(JellyfinUnavailableError("Jellyfin did not answer (ProviderUnavailableError)"))

    assert envelope["error"] == "JellyfinUnavailableError"
    # The fixed sentence, not the `{detail}` fallback a missing message row would produce.
    assert envelope["message"] == "Jellyfin is unreachable or not configured."


def test_the_route_is_published_with_both_its_parameters() -> None:
    document = create_app().openapi()

    assert SYNC_PATH in document["paths"]
    assert document["paths"][SYNC_PATH]["post"]["tags"] == ["library"]
    assert [p["name"] for p in document["paths"][SYNC_PATH]["post"]["parameters"]] == ["full", "since"]


async def test_the_route_answers_the_counts(db_session: AsyncSession) -> None:
    response = await _post(client_for(fixture_library()), db_session)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_KEYS
    assert (body["seen"], body["added"], body["updated"], body["removed"]) == (LIBRARY_ROWS, LIBRARY_ROWS, 0, 0)
    assert body["incremental"] is False


async def test_an_unconfigured_jellyfin_answers_503_not_500(db_session: AsyncSession) -> None:
    responder = fixture_library()

    response = await _post(client_for(responder, base_url=None), db_session)

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "JellyfinUnavailableError"
    assert body["message"] == "Jellyfin is unreachable or not configured."
    assert responder.requests == []


async def test_a_full_pass_is_asked_for_by_a_query_parameter(db_session: AsyncSession) -> None:
    responder = fixture_library()

    response = await _post(client_for(responder), db_session, full="true")

    assert response.status_code == 200
    assert response.json()["incremental"] is False
    assert CURSOR_PARAM not in responder.requests[0].url.params


async def test_a_caller_may_hand_the_previous_passs_stamp_back_as_since(db_session: AsyncSession) -> None:
    """R87's first step, reached through the wire: the cursor a scheduler would keep between passes."""
    responder = JellyfinLibrary()

    response = await _post(client_for(responder), db_session, since=A_CURSOR.isoformat())

    assert response.status_code == 200
    assert response.json()["incremental"] is True
    assert responder.requests[0].url.params[CURSOR_PARAM] == A_CURSOR.isoformat()


async def test_a_since_with_no_offset_is_refused_at_the_boundary(db_session: AsyncSession) -> None:
    """`last_seen_at` and `date_last_saved` are both `timestamptz`; an offsetless stamp is ambiguous by
    exactly the machine's timezone, so it is a 422 here rather than an asyncpg error inside a walk."""
    responder = JellyfinLibrary()

    response = await _post(client_for(responder), db_session, since=A_CURSOR_WITH_NO_OFFSET)

    assert response.status_code == 422
    assert "since" in response.text
    assert responder.requests == []


async def test_two_overlapping_syncs_do_not_race(engine: AsyncEngine) -> None:
    """R88. Without the advisory lock both passes see a row as absent and both INSERT it, and the loser
    lands on `uq_jellyfin_item_jellyfin_id` as a 500 rather than on a library that is simply already built."""
    async for sessions in _live_sessions(engine, 2):
        first, second = await asyncio.gather(
            _post(client_for(fixture_library()), sessions[0]),
            _post(client_for(fixture_library()), sessions[1]),
        )

        assert (first.status_code, second.status_code) == (200, 200)
        # One built the index; the other arrived after the lock and found it already there.
        assert sorted([first.json()["added"], second.json()["added"]]) == [0, LIBRARY_ROWS]
        assert first.json()["seen"] == second.json()["seen"] == LIBRARY_ROWS
        async with AsyncSession(bind=engine) as reader:
            rows = (await reader.execute(select(func.count()).select_from(JellyfinItem))).scalar_one()
        assert rows == LIBRARY_ROWS


@pytest.mark.parametrize("shape", ["synced", "unconfigured", "unreachable"])
async def test_nothing_about_the_media_server_reaches_the_browser(db_session: AsyncSession, shape: str) -> None:
    if shape == "unreachable":
        client = _an_unreachable_jellyfin()
    else:
        client = client_for(fixture_library(), base_url=None if shape == "unconfigured" else A_JELLYFIN_BASE_URL)

    response = await _post(client, db_session)

    assert response.status_code in {200, 503}
    for secret in NEVER_IN_A_BODY:
        assert secret not in response.text, f"{secret} leaked into a {response.status_code} body"
