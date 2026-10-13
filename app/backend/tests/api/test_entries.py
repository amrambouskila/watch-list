"""`GET /api/categories/{id}/entries` through the real application.

The projection is served *alongside* the workbook-backed `CategoryDetail`, so this module also asserts
that every pre-existing route still answers exactly as it did (CLAUDE.md sections 5.12 and 13.5).

The tests that read the projection need a real Postgres and skip loudly without one; the route's own
contract - the OpenAPI document, the 404 envelope, the boundary validation - needs none.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from library_choice import a_category
from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry
from tv_watchlist.data.session import get_session
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.reader import read_projection

ENTRIES_PATH: Final[str] = "/api/categories/{category_id}/entries"
A_SLUG_THE_LIBRARY_DOES_NOT_HOLD: Final[str] = "no-workbook-answers-to-this"

# CLAUDE.md section 5.12. Phase 1 adds a fifteenth route and changes none of these.
PRE_EXISTING_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("get", "/api/categories"),
        ("post", "/api/categories"),
        ("get", "/api/categories/{category_id}"),
        ("delete", "/api/categories/{category_id}"),
        ("post", "/api/categories/{category_id}/rename"),
        ("post", "/api/categories/{category_id}/watch-column"),
        ("post", "/api/categories/{category_id}/rows"),
        ("patch", "/api/categories/{category_id}/rows/{row}"),
        ("delete", "/api/categories/{category_id}/rows/{row}"),
        ("post", "/api/chat/sessions"),
        ("post", "/api/chat/sessions/{session_id}/messages"),
        ("post", "/api/chat/proposals/{proposal_id}/approve"),
        ("post", "/api/chat/proposals/{proposal_id}/hero/{choice}"),
        ("delete", "/api/chat/sessions/{session_id}"),
    }
)
# CLAUDE.md section 5.4, unchanged by Phase 1: the workbook stays the editing contract.
CATEGORY_DETAIL_PROPERTIES: Final[frozenset[str]] = frozenset(
    {
        "id",
        "name",
        "file_name",
        "sheet_title",
        "accent",
        "mtime",
        "has_watch_column",
        "locked_by_excel",
        "hero_url",
        "counts",
        "columns",
        "rows",
        "reference_sheets",
    }
)


def _wired(catalog: Catalog, settings: Settings, session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def offline_client(catalog: Catalog, settings: Settings) -> AsyncIterator[AsyncClient]:
    """No database: the session is unbound, so anything that reaches it fails loudly instead of quietly."""
    async with _wired(catalog, settings, AsyncSession()) as client:
        yield client


@pytest.fixture
async def client(catalog: Catalog, settings: Settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async with _wired(catalog, settings, db_session) as client:
        yield client


async def _seeded(session: AsyncSession, library: Path) -> tuple[str, list[dict[str, str]]]:
    """One category projected out of a real workbook, so `cells` can be compared to what the sheet carries."""
    facts = a_category()
    detail = read_projection(facts.copied_into(library)).detail
    category = Category(
        slug=detail.id,
        file_name=detail.file_name,
        sheet_title=detail.sheet_title,
        accent=detail.accent,
        workbook_mtime=detail.mtime,
    )
    session.add(category)
    await session.flush()
    session.add_all(
        CuratedEntry(
            category_id=category.id,
            position=position,
            sheet_row=row.row,
            unit_kind=UnitKind.UNKNOWN,
            resolution_state=ResolutionState.UNRESOLVED,
            raw_cells=row.cells,
            raw_title=row.cells.get("title", ""),
        )
        for position, row in enumerate(detail.rows, start=1)
    )
    await session.flush()
    return detail.id, [row.cells for row in detail.rows]


def test_the_projection_route_is_in_the_applications_openapi_document() -> None:
    paths = create_app().openapi()["paths"]

    assert ENTRIES_PATH in paths
    assert "get" in paths[ENTRIES_PATH]


def test_every_pre_existing_route_is_unchanged() -> None:
    document = create_app().openapi()
    published = {(method, path) for path, methods in document["paths"].items() for method in methods}

    assert PRE_EXISTING_ROUTES <= published
    assert set(document["components"]["schemas"]["CategoryDetail"]["properties"]) == CATEGORY_DETAIL_PROPERTIES


def test_a_single_path_segment_cannot_swallow_the_entries_suffix() -> None:
    """`/{category_id}` and `/{category_id}/entries` are different shapes, so include order cannot matter."""
    paths = create_app().openapi()["paths"]

    assert "/api/categories/{category_id}" in paths
    assert ENTRIES_PATH in paths


async def test_an_unknown_category_is_404_with_the_standard_envelope(offline_client: AsyncClient) -> None:
    response = await offline_client.get(f"/api/categories/{A_SLUG_THE_LIBRARY_DOES_NOT_HOLD}/entries")

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "CategoryNotFoundError"
    assert body["detail"] == A_SLUG_THE_LIBRARY_DOES_NOT_HOLD
    assert A_SLUG_THE_LIBRARY_DOES_NOT_HOLD in body["message"]


@pytest.mark.parametrize(
    "query",
    [
        f"limit={MAX_ENTRIES_PAGE_SIZE + 1}",
        "limit=0",
        "limit=-1",
        "offset=-1",
        "limit=all",
    ],
    ids=["over-the-cap", "zero", "negative-limit", "negative-offset", "not-a-number"],
)
async def test_the_page_window_is_validated_at_the_boundary(offline_client: AsyncClient, query: str) -> None:
    slug = a_category().category_id

    response = await offline_client.get(f"/api/categories/{slug}/entries?{query}")

    assert response.status_code == 422


async def test_a_never_ingested_category_answers_an_empty_list_not_an_error(client: AsyncClient) -> None:
    """Tracked but not available here is a state, not an error (CLAUDE.md section 18.2)."""
    slug = a_category().category_id

    response = await client.get(f"/api/categories/{slug}/entries")

    assert response.status_code == 200
    assert response.json() == []


async def test_the_projection_is_served_in_sheet_order_with_watch_row_shaped_cells(
    client: AsyncClient, db_session: AsyncSession, library: Path
) -> None:
    slug, cells = await _seeded(db_session, library)

    body = (await client.get(f"/api/categories/{slug}/entries")).json()

    assert [entry["position"] for entry in body] == list(range(1, len(cells) + 1))
    # The whole point of the alias: one renderer serves a row from either store.
    assert [entry["cells"] for entry in body] == cells


async def test_an_unresolved_entry_is_a_first_class_row(
    client: AsyncClient, db_session: AsyncSession, library: Path
) -> None:
    slug, cells = await _seeded(db_session, library)

    body = (await client.get(f"/api/categories/{slug}/entries")).json()

    assert body[0]["resolution_state"] == ResolutionState.UNRESOLVED.value
    assert body[0]["title"] is None
    assert body[0]["progress"]["kind"] == "unset"
    assert body[0]["cells"] == cells[0]


async def test_limit_and_offset_page_in_position_order(
    client: AsyncClient, db_session: AsyncSession, library: Path
) -> None:
    slug, cells = await _seeded(db_session, library)
    assert len(cells) >= 4

    body = (await client.get(f"/api/categories/{slug}/entries?limit=2&offset=2")).json()

    assert [entry["position"] for entry in body] == [3, 4]


async def test_the_workbook_route_still_answers_beside_the_projection(
    client: AsyncClient, db_session: AsyncSession, library: Path
) -> None:
    """The two live side by side: `CategoryDetail` is still the editing contract."""
    slug, cells = await _seeded(db_session, library)

    detail = (await client.get(f"/api/categories/{slug}")).json()
    entries = (await client.get(f"/api/categories/{slug}/entries")).json()

    assert set(detail) == CATEGORY_DETAIL_PROPERTIES
    assert [row["cells"] for row in detail["rows"]] == [entry["cells"] for entry in entries]
