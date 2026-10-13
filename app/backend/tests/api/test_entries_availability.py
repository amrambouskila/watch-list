from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from episode_join_support import a_film, an_entry, file_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from library_choice import a_category
from provider_fixtures import JELLYFIN, fixture_text_response, jellyfin_client_for
from review_support import seeded_category, tmdb_runtime
from tv_watchlist.api.dependencies import get_catalog, get_ingest_runtime, get_jellyfin_client
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.data.enums import JellyfinItemKind, UnitKind
from tv_watchlist.data.models import JellyfinItem
from tv_watchlist.data.session import get_session
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog


@pytest.fixture
async def availability_client(
    catalog: Catalog, settings: Settings, db_session: AsyncSession, engine: AsyncEngine
) -> AsyncIterator[AsyncClient]:
    jellyfin, _ = jellyfin_client_for(fixture_text_response(JELLYFIN, "health"))
    runtime = tmdb_runtime(settings, catalog, engine, httpx.Response(200, json={"results": [], "total_pages": 1}))
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_jellyfin_client] = lambda: jellyfin
    app.dependency_overrides[get_ingest_runtime] = lambda: runtime
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await jellyfin.aclose()
        await runtime.aclose()


@pytest.mark.parametrize("endpoint", ["category", "review"])
async def test_listing_routes_serve_all_three_states_with_exactly_the_two_new_wire_fields(
    availability_client: AsyncClient, db_session: AsyncSession, endpoint: str
) -> None:
    slug = a_category().category_id
    category = await seeded_category(db_session, slug)
    expected: list[tuple[str, str | None]] = []
    for count, state in enumerate(("not_in_library", "in_library", "ambiguous")):
        title = await a_film(db_session, f"Movie {count}", tmdb_id=4242 + count)
        await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE, position=count + 1)
        files = [
            JellyfinItem(
                jellyfin_id=file_id((count + 1) * 100 + index),
                kind=JellyfinItemKind.MOVIE,
                name=title.name,
                tmdb_id=title.tmdb_id,
            )
            for index in range(count)
        ]
        db_session.add_all(files)
        await db_session.flush()
        expected.append((state, str(files[0].id) if count == 1 else None))
    path = f"/api/categories/{slug}/entries" if endpoint == "category" else "/api/review/entries"
    response = await availability_client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert [(row["availability"], row["jellyfin_item_id"]) for row in body] == expected
    assert all("notice" not in row for row in body)
    assert all(row["category_slug"] == slug for row in body)


async def test_a_review_decision_recomputes_availability_in_its_response(
    availability_client: AsyncClient, db_session: AsyncSession
) -> None:
    category = await seeded_category(db_session, a_category().category_id)
    title = await a_film(db_session, "A Film", tmdb_id=4242)
    entry = await an_entry(db_session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    file = JellyfinItem(jellyfin_id=file_id(1), kind=JellyfinItemKind.MOVIE, name=title.name, tmdb_id=title.tmdb_id)
    db_session.add(file)
    await db_session.flush()

    confirmed = await availability_client.post(f"/api/review/entries/{entry.id}", json={"action": "confirm"})
    assert confirmed.status_code == 200
    assert confirmed.json()["availability"] == "in_library"
    assert confirmed.json()["jellyfin_item_id"] == str(file.id)

    rejected = await availability_client.post(f"/api/review/entries/{entry.id}", json={"action": "reject"})
    assert rejected.status_code == 200
    assert rejected.json()["availability"] == "not_in_library"
    assert rejected.json()["jellyfin_item_id"] is None


async def test_a_retry_response_carries_computed_availability(
    availability_client: AsyncClient, db_session: AsyncSession
) -> None:
    category = await seeded_category(db_session, a_category().category_id)
    entry = await an_entry(db_session, category, title_id=None, unit_kind=UnitKind.UNKNOWN)
    entry.raw_title = "A Film No Catalogue Carries"
    await db_session.flush()
    response = await availability_client.post(f"/api/review/entries/{entry.id}/retry")
    assert response.status_code == 200
    assert response.json()["availability"] == "not_in_library"
    assert response.json()["jellyfin_item_id"] is None
