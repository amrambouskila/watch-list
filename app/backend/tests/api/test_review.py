"""`/api/review` through the real application: the queue, and the three decisions a human can make.

The route's own contract - the OpenAPI document, the boundary validation, the refusal envelope - needs no
database. Everything that reads or writes the projection runs against a real Postgres and skips loudly
without one; a mocked database would prove only that the mock agrees with itself (CLAUDE.md 16.4).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, Final

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from library_choice import a_category
from provider_fixtures import TMDB, fixture_response
from review_support import (
    ABSOLUTE,
    AIRED,
    ONE_PIECE_TMDB_ID,
    seeded_category,
    seeded_entry,
    seeded_episodes,
    seeded_numbering,
    seeded_title,
    tmdb_runtime,
)
from tv_watchlist.api.dependencies import get_catalog, get_ingest_runtime
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.constants import MAX_ENTRIES_PAGE_SIZE, REVIEW_NOTE_PREFIX
from tv_watchlist.data.enums import MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import CuratedEntry, CuratedEntryItem
from tv_watchlist.data.session import build_engine, get_session
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog

QUEUE_PATH: Final[str] = "/api/review/entries"
DECISION_PATH: Final[str] = "/api/review/entries/{entry_id}"
AN_UNKNOWN_ENTRY: Final[str] = "00000000-0000-4000-8000-000000000000"
SPAN_START: Final[int] = 19
SPAN_END: Final[int] = 53
SPAN_LENGTH: Final[int] = SPAN_END - SPAN_START + 1
A_DVD_ORDER: Final[str] = "dvd"
A_RESOLVER_CLAUSE: Final[str] = "auto: 0.50 on title and year"


def _wired(catalog: Catalog, settings: Settings, session: AsyncSession, runtime: IngestRuntime) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_ingest_runtime] = lambda: runtime
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def runtime(settings: Settings, catalog: Catalog, engine: AsyncEngine) -> AsyncIterator[IngestRuntime]:
    built = tmdb_runtime(
        settings,
        catalog,
        engine,
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_external_ids"),
    )
    yield built
    await built.aclose()


@pytest.fixture
async def client(
    catalog: Catalog, settings: Settings, db_session: AsyncSession, runtime: IngestRuntime
) -> AsyncIterator[AsyncClient]:
    async with _wired(catalog, settings, db_session, runtime) as wired:
        yield wired


@pytest.fixture
async def offline_client(catalog: Catalog, settings: Settings) -> AsyncIterator[AsyncClient]:
    """No database: the session is unbound, so anything reaching it fails loudly rather than quietly.

    The engine is built, never connected - `create_async_engine` opens no socket - so the contract half
    of this module runs on a workstation with no Postgres at all.
    """
    unconnected = build_engine(settings.database_url)
    built = tmdb_runtime(settings, catalog, unconnected, token=None)
    async with _wired(catalog, settings, AsyncSession(), built) as wired:
        yield wired
    await built.aclose()
    await unconnected.dispose()


async def _items(session: AsyncSession, entry_id: str) -> int:
    statement = (
        select(func.count())
        .select_from(CuratedEntryItem)
        .where(CuratedEntryItem.curated_entry_id == uuid.UUID(entry_id))
    )
    return (await session.execute(statement)).scalar_one()


# -- the contract, without a database ----------------------------------------------------------------


def test_both_review_routes_are_in_the_applications_openapi_document() -> None:
    paths = create_app().openapi()["paths"]

    assert "get" in paths[QUEUE_PATH]
    assert "post" in paths["/api/review/entries/{entry_id}"]


@pytest.mark.parametrize(
    "query",
    [f"limit={MAX_ENTRIES_PAGE_SIZE + 1}", "limit=0", "offset=-1", "limit=all", "state=settled"],
    ids=["over-the-cap", "zero", "negative-offset", "not-a-number", "not-a-state"],
)
async def test_the_queue_window_is_validated_at_the_boundary(offline_client: AsyncClient, query: str) -> None:
    response = await offline_client.get(f"{QUEUE_PATH}?{query}")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"action": "confirm", "tmdb_id": ONE_PIECE_TMDB_ID},
        {"action": "correct", "media_type": "tv"},
        {"action": "correct", "media_type": "tv", "tmdb_id": ONE_PIECE_TMDB_ID, "span_start": 53, "span_end": 19},
        {"action": "correct", "media_type": "tv", "tmdb_id": ONE_PIECE_TMDB_ID, "unknown": "field"},
    ],
    ids=["confirm-with-a-title", "correct-without-a-tmdb-id", "reversed-span", "an-unknown-field"],
)
async def test_an_incoherent_decision_is_refused_at_the_boundary(
    offline_client: AsyncClient, body: dict[str, Any]
) -> None:
    response = await offline_client.post(DECISION_PATH.format(entry_id=AN_UNKNOWN_ENTRY), json=body)

    assert response.status_code == 422


async def test_an_entry_id_that_is_not_a_uuid_is_refused(offline_client: AsyncClient) -> None:
    response = await offline_client.post(DECISION_PATH.format(entry_id="not-a-uuid"), json={"action": "confirm"})

    assert response.status_code == 422


# -- the queue ---------------------------------------------------------------------------------------


async def test_the_queue_lists_unresolved_and_auto_worst_first(client: AsyncClient, db_session: AsyncSession) -> None:
    category = await seeded_category(db_session, "route-queue-order")
    await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO, confidence=Decimal("0.80"))
    await seeded_entry(db_session, category, position=2, state=ResolutionState.UNRESOLVED)
    await seeded_entry(db_session, category, position=3, state=ResolutionState.AUTO, confidence=Decimal("0.50"))
    await seeded_entry(db_session, category, position=4, state=ResolutionState.CONFIRMED, confidence=Decimal("1.00"))

    body = (await client.get(f"{QUEUE_PATH}?category_id={category.slug}")).json()

    assert [entry["position"] for entry in body] == [2, 3, 1]
    assert [entry["resolution_confidence"] for entry in body] == [None, 0.5, 0.8]


async def test_the_queue_is_filterable_by_category_and_state(client: AsyncClient, db_session: AsyncSession) -> None:
    first = await seeded_category(db_session, "route-queue-first")
    second = await seeded_category(db_session, "route-queue-second")
    await seeded_entry(db_session, first, position=1, state=ResolutionState.UNRESOLVED)
    await seeded_entry(db_session, first, position=2, state=ResolutionState.AUTO, confidence=Decimal("0.65"))
    await seeded_entry(db_session, second, position=1, state=ResolutionState.UNRESOLVED)

    scoped = (await client.get(f"{QUEUE_PATH}?category_id={first.slug}")).json()
    by_state = (await client.get(f"{QUEUE_PATH}?category_id={first.slug}&state=auto")).json()

    assert [entry["position"] for entry in scoped] == [1, 2]
    assert [entry["resolution_state"] for entry in by_state] == ["auto"]


async def test_the_queue_carries_the_verbatim_cells_a_reviewer_reads(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An unresolved row is a first-class row: the sheet's own text is what a human decides from."""
    category = await seeded_category(db_session, "route-queue-cells")
    await seeded_entry(db_session, category, position=1, raw_title="Marvel One-Shot: The Consultant")

    body = (await client.get(f"{QUEUE_PATH}?category_id={category.slug}")).json()

    assert body[0]["cells"] == {"title": "Marvel One-Shot: The Consultant"}
    assert body[0]["title"] is None
    assert body[0]["progress"]["kind"] == "unset"


# -- the decisions -----------------------------------------------------------------------------------


async def test_confirming_pins_the_entry_and_it_leaves_the_queue(client: AsyncClient, db_session: AsyncSession) -> None:
    category = await seeded_category(db_session, "route-confirm")
    entry = await seeded_entry(
        db_session,
        category,
        position=1,
        state=ResolutionState.AUTO,
        confidence=Decimal("0.5"),
        note=A_RESOLVER_CLAUSE,
    )

    response = await client.post(
        DECISION_PATH.format(entry_id=entry.id), json={"action": "confirm", "note": "checked the box set"}
    )
    queue = (await client.get(f"{QUEUE_PATH}?category_id={category.slug}")).json()

    assert response.status_code == 200
    body = response.json()
    assert body["resolution_state"] == "confirmed"
    assert body["resolution_confidence"] == 1.0
    # Ruling 45: the note is served, not merely stored. A reviewer sees what was already tried and what
    # the last human said about it, and the resolver's own sentence survives beside the review clause.
    assert body["resolution_note"].startswith(A_RESOLVER_CLAUSE)
    assert f"{REVIEW_NOTE_PREFIX}confirm - checked the box set" in body["resolution_note"]
    assert queue == []


async def test_correcting_re_points_the_entry_and_rebuilds_its_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category = await seeded_category(db_session, "route-correct")
    entry = await seeded_entry(db_session, category, position=1, raw_title="One Piece")
    title = await seeded_title(db_session, name="One Piece", tmdb_id=ONE_PIECE_TMDB_ID)
    await seeded_numbering(db_session, title, await seeded_episodes(db_session, title), order_type=ABSOLUTE)

    response = await client.post(
        DECISION_PATH.format(entry_id=entry.id),
        json={
            "action": "correct",
            "media_type": MediaType.TV.value,
            "tmdb_id": ONE_PIECE_TMDB_ID,
            "unit_kind": UnitKind.EPISODES.value,
            "order_type": ABSOLUTE,
            "span_start": SPAN_START,
            "span_end": SPAN_END,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolution_state"] == "confirmed"
    assert body["title"]["tmdb_id"] == ONE_PIECE_TMDB_ID
    assert await _items(db_session, body["id"]) == SPAN_LENGTH


async def test_correcting_with_an_order_the_title_lacks_is_409(client: AsyncClient, db_session: AsyncSession) -> None:
    category = await seeded_category(db_session, "route-correct-order")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO)
    title = await seeded_title(db_session, name="One Piece", tmdb_id=ONE_PIECE_TMDB_ID)
    episodes = await seeded_episodes(db_session, title)
    await seeded_numbering(db_session, title, episodes, order_type=ABSOLUTE)
    await seeded_numbering(db_session, title, episodes, order_type=AIRED)

    response = await client.post(
        DECISION_PATH.format(entry_id=entry.id),
        json={
            "action": "correct",
            "media_type": MediaType.TV.value,
            "tmdb_id": ONE_PIECE_TMDB_ID,
            "order_type": A_DVD_ORDER,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"] == "ResolutionConflictError"
    assert entry.resolution_state is ResolutionState.AUTO


async def test_correcting_without_a_configured_provider_is_409(
    catalog: Catalog, settings: Settings, db_session: AsyncSession, engine: AsyncEngine
) -> None:
    category = await seeded_category(db_session, "route-correct-unconfigured")
    entry = await seeded_entry(db_session, category, position=1)
    built = tmdb_runtime(settings, catalog, engine, token=None)

    try:
        async with _wired(catalog, settings, db_session, built) as client:
            response = await client.post(
                DECISION_PATH.format(entry_id=entry.id),
                json={"action": "correct", "media_type": MediaType.TV.value, "tmdb_id": ONE_PIECE_TMDB_ID},
            )
    finally:
        await built.aclose()

    assert response.status_code == 409
    assert response.json()["error"] == "ResolutionConflictError"


async def test_rejecting_clears_the_title_and_the_items_but_keeps_the_row_listed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # A slug the library really holds, because the projection route resolves the workbook behind it.
    category = await seeded_category(db_session, a_category().category_id)
    title = await seeded_title(db_session, name="Something else entirely")
    entry = await seeded_entry(
        db_session, category, position=1, state=ResolutionState.AUTO, unit_kind=UnitKind.MOVIE, title=title
    )

    response = await client.post(
        DECISION_PATH.format(entry_id=entry.id), json={"action": "reject", "note": "a featurette, not a film"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolution_state"] == "rejected"
    assert body["title"] is None
    assert await _items(db_session, body["id"]) == 0
    # It leaves the review queue, and stays a row of its category's projection.
    assert (await client.get(f"{QUEUE_PATH}?category_id={category.slug}")).json() == []
    listed = (await client.get(f"/api/categories/{category.slug}/entries")).json()
    assert [row["position"] for row in listed] == [1]


async def test_an_unknown_entry_is_404_with_its_own_error_code(client: AsyncClient) -> None:
    response = await client.post(DECISION_PATH.format(entry_id=AN_UNKNOWN_ENTRY), json={"action": "confirm"})

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "EntryNotFoundError"
    assert AN_UNKNOWN_ENTRY in body["detail"]


async def test_a_confirmed_decision_survives_a_second_read(client: AsyncClient, db_session: AsyncSession) -> None:
    """The write is committed by the request that made it, not left for the next one to find missing."""
    category = await seeded_category(db_session, "route-confirm-persists")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO)

    await client.post(DECISION_PATH.format(entry_id=entry.id), json={"action": "confirm"})
    stored = await db_session.scalar(select(CuratedEntry).where(CuratedEntry.id == entry.id))

    assert stored is not None
    assert stored.resolution_state is ResolutionState.CONFIRMED
