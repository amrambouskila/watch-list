from __future__ import annotations

import uuid

import pytest
from episode_join_support import a_category, a_show, an_entry
from sqlalchemy.ext.asyncio import AsyncSession

from playback_server import PlaybackServer
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import UnitKind
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.main import create_app
from tv_watchlist.models.playback_item_read import PlaybackItemRead


async def test_items_route_pages_in_stored_order_and_retains_missing_slots(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    title = await a_show(db_session, "A Show", episodes=3, tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.SERIES)
    await rebuild_items(db_session, category.id)
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/entries/{entry.id}/items", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    assert len(response.json()) == 1
    row = response.json()[0]
    assert set(row) == set(PlaybackItemRead.model_fields)
    assert row["position_in_entry"] == row["absolute_position"] == 2
    assert row["availability"] == "not_in_library" and row["jellyfin_item_id"] is None
    assert [request.url.path for request in server.requests] == ["/health"]


@pytest.mark.parametrize("shape", ["unknown", "removed", "retired"])
async def test_missing_live_entry_is_404_without_upstream_requests(db_session: AsyncSession, shape: str) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    if shape == "removed":
        entry.removed_at = utcnow()
    if shape == "retired":
        category.retired_at = utcnow()
    await db_session.flush()
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/entries/{uuid.uuid4() if shape == 'unknown' else entry.id}/items")
    assert response.status_code == 404
    assert response.json()["error"] == "EntryNotFoundError"
    assert not server.requests


@pytest.mark.parametrize("configured", [False, True])
async def test_disabled_or_unhealthy_jellyfin_refuses_items_with_503(
    db_session: AsyncSession, configured: bool
) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    server = PlaybackServer(configured=configured, healthy=False)
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/entries/{entry.id}/items")
    assert response.status_code == 503
    assert response.json()["error"] == "JellyfinUnavailableError"


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1", "limit=abc"])
async def test_paging_parameters_are_bounded(db_session: AsyncSession, query: str) -> None:
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/entries/{uuid.uuid4()}/items?{query}")
    assert response.status_code == 422
    assert not server.requests


def test_both_playback_routes_are_published_in_openapi() -> None:
    paths = create_app().openapi()["paths"]
    items = paths["/api/playback/entries/{entry_id}/items"]["get"]
    assert items["tags"] == ["playback"]
    assert [parameter["name"] for parameter in items["parameters"]] == ["entry_id", "limit", "offset"]
    assert paths["/api/playback/{jellyfin_item_id}/stream"]["get"]["tags"] == ["playback"]


async def test_a_closed_jellyfin_pool_refuses_items_without_attempting_health(db_session: AsyncSession) -> None:
    category = await a_category(db_session)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    server = PlaybackServer()
    await server.client.aclose()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/entries/{entry.id}/items")
    assert response.status_code == 503
    assert not server.requests
