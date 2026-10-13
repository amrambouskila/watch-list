"""`POST /api/review/entries/{entry_id}/retry` through the real application: one row re-resolved by hand.

R71's control, and the reason it exists: an untouched workbook is skipped, so nothing re-resolves a row a
provider outage left `unresolved` except the next real edit. The queue is where a human is already looking
at that row, so the retry is offered there - and it refuses a `confirmed` row, because a human decision is
not something a heuristic may take back.

Every provider answer is a recorded body replayed through the transport seam; nothing here reaches TMDB.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Final

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import A_RECORDED_KEY, A_RECORDED_PIN, TMDB, fixture_response
from review_support import (
    ONE_PIECE_TMDB_ID,
    recording_tmdb_runtime,
    seeded_category,
    seeded_entry,
    seeded_title,
    tmdb_runtime,
)
from tv_watchlist.api.dependencies import get_catalog, get_ingest_runtime
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.data.episode_order_lock import try_episode_order_locks
from tv_watchlist.data.models import Category, CuratedEntry, Title
from tv_watchlist.data.session import build_engine, get_session
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.resolution_review import NOT_CONFIGURED
from tv_watchlist.workbook.naming import slugify

RETRY_PATH: Final[str] = "/api/review/entries/{entry_id}/retry"
AN_UNKNOWN_ENTRY: Final[str] = "00000000-0000-4000-8000-000000000000"
ONE_PIECE: Final[str] = "One Piece"
A_SPAN: Final[str] = "E19–53"
# The sheet's own `Release` cell. Without it three "One Piece" series score identically and the
# resolver leaves the row for a human (Ruling 35) - which is a different test than this one.
A_RELEASE_YEAR: Final[str] = "1999"
# The note a pass left behind when the token was absent - exactly the row this control exists for.
A_STALE_NOTE: Final[str] = "TMDB not configured"
# Nothing answers for it, so the resolve ends unresolved rather than pointing the row somewhere wrong.
A_ROW_NOTHING_ANSWERS_FOR: Final[str] = "A Row No Catalogue Carries"
# What `E19-53` really produces once the resolver has matched the series: T19's parse, stored.
AN_EPISODE_SPAN: Final[tuple[str, str, int, int]] = ("episodes", "absolute", 19, 53)
# Ruling 27: a blank `Unit` states no kind, so the kind follows the Type cell and then the match. 66
# Misc_Anime rows are this shape, and reading them as films is the failure this guards.
AN_EPISODIC_TYPE_CELL: Final[str] = "TV"


def _full_state(entry: CuratedEntry) -> tuple[object, ...]:
    """Everything a resolve could move on a row, so "untouched" means untouched rather than mostly so.

    `updated_at` is in here deliberately: an UPDATE that rewrote a column to the value it already held
    would still bump it, which is the difference between a row nothing touched and one that was written
    to and happened to come out the same.
    """
    return (
        entry.resolution_state,
        entry.resolution_confidence,
        entry.resolution_note,
        entry.title_id,
        entry.unit_kind,
        entry.order_type,
        entry.order_label,
        entry.span_start,
        entry.span_end,
        entry.season_number,
        entry.last_seen_at,
        entry.updated_at,
    )


async def _reread(session: AsyncSession, entry_id: uuid.UUID) -> CuratedEntry:
    """The row as the database holds it now, not as the identity map remembers it."""
    statement = select(CuratedEntry).where(CuratedEntry.id == entry_id).execution_options(populate_existing=True)
    entry = (await session.execute(statement)).scalar_one()
    return entry


def _wired(catalog: Catalog, settings: Settings, session: AsyncSession, runtime: IngestRuntime) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_ingest_runtime] = lambda: runtime
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _one_piece_answers() -> tuple[httpx.Response, ...]:
    """The search that finds the series, the series document, its external ids - then nothing.

    The 404 tail is deliberate: `MockResponder` repeats its last answer, so every call the ingest makes
    beyond these three is refused the way an outage refuses one, and each of those legs is already built
    to report that nothing arrived rather than to raise. The test stays about the retry.
    """
    return (
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_external_ids"),
        httpx.Response(404, json={}),
    )


@pytest.fixture
async def runtime(settings: Settings, catalog: Catalog, engine: AsyncEngine) -> AsyncIterator[IngestRuntime]:
    built = tmdb_runtime(settings, catalog, engine, *_one_piece_answers())
    yield built
    await built.aclose()


@pytest.fixture
async def client(
    catalog: Catalog, settings: Settings, db_session: AsyncSession, runtime: IngestRuntime
) -> AsyncIterator[AsyncClient]:
    async with _wired(catalog, settings, db_session, runtime) as wired:
        yield wired


async def _an_unresolved_one_piece_row(session: AsyncSession, slug: str) -> CuratedEntry:
    category = await seeded_category(session, slug)
    return await seeded_entry(
        session,
        category,
        position=1,
        raw_title=ONE_PIECE,
        raw_unit=A_SPAN,
        raw_release=A_RELEASE_YEAR,
        note=A_STALE_NOTE,
    )


# -- the contract, without a database ----------------------------------------------------------------


def test_the_retry_route_is_in_the_applications_openapi_document() -> None:
    assert "post" in create_app().openapi()["paths"][RETRY_PATH]


async def test_an_entry_id_that_is_not_a_uuid_is_refused(catalog: Catalog, settings: Settings) -> None:
    """No database is reached: the path parameter is refused at the boundary."""
    unconnected = build_engine(settings.database_url)
    built = tmdb_runtime(settings, catalog, unconnected, token=None)
    try:
        async with _wired(catalog, settings, AsyncSession(), built) as client:
            response = await client.post(RETRY_PATH.format(entry_id="not-a-uuid"))
    finally:
        await built.aclose()
        await unconnected.dispose()

    assert response.status_code == 422


# -- the retry ---------------------------------------------------------------------------------------


async def test_a_retry_re_resolves_one_entry_and_answers_the_row_as_it_now_stands(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    entry = await _an_unresolved_one_piece_row(db_session, slugify(ONE_PIECE))

    response = await client.post(RETRY_PATH.format(entry_id=entry.id))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(entry.id)
    assert body["resolution_state"] == ResolutionState.AUTO.value
    assert (body["title"]["tmdb_id"], body["title"]["name"]) == (ONE_PIECE_TMDB_ID, ONE_PIECE)
    # The stored `Unit` cell was parsed, not ignored: the span the sheet wrote is the span on the row.
    assert (body["unit_kind"], body["order_type"], body["span_start"], body["span_end"]) == AN_EPISODE_SPAN
    # The row says why it is where it is NOW, so the note a dead provider left is gone rather than kept.
    assert body["resolution_note"] != A_STALE_NOTE
    assert body["resolution_confidence"] is not None
    assert body["category_slug"] == slugify(ONE_PIECE)


async def test_a_retry_that_still_finds_nothing_leaves_the_row_unresolved_with_the_new_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A retry is an answer, not a promise: a row nothing answers for stays in the queue and says so."""
    category = await seeded_category(db_session, "retry-nothing-answers")
    entry = await seeded_entry(
        db_session, category, position=1, raw_title=A_ROW_NOTHING_ANSWERS_FOR, raw_unit=A_SPAN, note=A_STALE_NOTE
    )

    response = await client.post(RETRY_PATH.format(entry_id=entry.id))

    assert response.status_code == 200
    body = response.json()
    assert body["resolution_state"] == ResolutionState.UNRESOLVED.value
    assert body["title"] is None
    assert body["resolution_note"] != A_STALE_NOTE


async def test_a_retry_does_not_touch_any_other_entry(client: AsyncClient, db_session: AsyncSession) -> None:
    category = await seeded_category(db_session, "retry-one-row-only")
    retried = await seeded_entry(
        db_session,
        category,
        position=1,
        raw_title=ONE_PIECE,
        raw_unit=A_SPAN,
        raw_release=A_RELEASE_YEAR,
        note=A_STALE_NOTE,
    )
    untouched = await seeded_entry(
        db_session,
        category,
        position=2,
        raw_title=ONE_PIECE,
        raw_unit=A_SPAN,
        raw_release=A_RELEASE_YEAR,
        note=A_STALE_NOTE,
    )

    before = _full_state(await _reread(db_session, untouched.id))

    response = await client.post(RETRY_PATH.format(entry_id=retried.id))

    assert response.status_code == 200
    assert _full_state(await _reread(db_session, untouched.id)) == before
    # And the row that was retried really did move, or the comparison above would prove nothing.
    assert (await _reread(db_session, retried.id)).resolution_state is ResolutionState.AUTO


@pytest.mark.parametrize("state", [ResolutionState.CONFIRMED, ResolutionState.REJECTED], ids=["confirmed", "rejected"])
async def test_a_retry_on_a_human_decided_entry_is_409_and_writes_nothing(
    catalog: Catalog, settings: Settings, db_session: AsyncSession, engine: AsyncEngine, state: ResolutionState
) -> None:
    """Rule 5: a human decision is never overwritten by a heuristic, and a retry is a heuristic.

    `rejected` is in here beside `confirmed` because it is the more dangerous of the two: a reject says
    there is no right match, so a re-resolve that found one would store exactly the title a person had
    just refused.
    """
    category = await seeded_category(db_session, f"retry-{state.value}")
    entry = await seeded_entry(
        db_session,
        category,
        position=1,
        state=state,
        raw_title=ONE_PIECE,
        raw_unit=A_SPAN,
        raw_release=A_RELEASE_YEAR,
        note=A_STALE_NOTE,
    )
    before = _full_state(await _reread(db_session, entry.id))
    built, responder = recording_tmdb_runtime(settings, catalog, engine, *_one_piece_answers())

    try:
        async with _wired(catalog, settings, db_session, built) as client:
            response = await client.post(RETRY_PATH.format(entry_id=entry.id))
    finally:
        await built.aclose()

    assert response.status_code == 409
    assert response.json()["error"] == "ResolutionConflictError"
    assert _full_state(await _reread(db_session, entry.id)) == before
    # Refused before anything is asked of TMDB, so the refusal costs no search out of the budget.
    assert responder.requests == []


async def test_a_retry_on_an_unknown_entry_is_404(client: AsyncClient) -> None:
    response = await client.post(RETRY_PATH.format(entry_id=AN_UNKNOWN_ENTRY))

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "EntryNotFoundError"
    assert AN_UNKNOWN_ENTRY in body["detail"]


async def test_a_retry_without_a_configured_provider_is_409(
    catalog: Catalog, settings: Settings, db_session: AsyncSession, engine: AsyncEngine
) -> None:
    """An absent token is a disabled feature, and a retry that silently changed nothing would look like one."""
    entry = await _an_unresolved_one_piece_row(db_session, "retry-unconfigured")
    before = _full_state(await _reread(db_session, entry.id))
    built, responder = recording_tmdb_runtime(settings, catalog, engine, token=None)

    try:
        async with _wired(catalog, settings, db_session, built) as client:
            response = await client.post(RETRY_PATH.format(entry_id=entry.id))
    finally:
        await built.aclose()

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "ResolutionConflictError"
    assert NOT_CONFIGURED in body["detail"]
    assert _full_state(await _reread(db_session, entry.id)) == before
    assert responder.requests == []


async def test_a_retried_row_survives_a_second_read(client: AsyncClient, db_session: AsyncSession) -> None:
    """The write is committed by the request that made it, as every other review decision is."""
    entry = await _an_unresolved_one_piece_row(db_session, "retry-persists")

    await client.post(RETRY_PATH.format(entry_id=entry.id))
    # Refreshed, or the identity map would answer with the instance the request already wrote to and
    # the read would prove nothing about what reached the database.
    stored = await _reread(db_session, entry.id)

    assert stored.resolution_state is ResolutionState.AUTO
    assert stored.title_id is not None


async def test_a_retry_on_a_soft_deleted_entry_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    """A row the sheet dropped is gone, not editable: the chain is soft-deleted, never purged."""
    entry = await _an_unresolved_one_piece_row(db_session, "retry-removed")
    entry.removed_at = utcnow()
    await db_session.flush()

    response = await client.post(RETRY_PATH.format(entry_id=entry.id))

    assert response.status_code == 404
    assert response.json()["error"] == "EntryNotFoundError"


async def test_a_blank_unit_takes_its_kind_from_the_stored_type_cell(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Ruling 27, through the stored row: 66 Misc_Anime rows leave `Unit` empty and name their kind in `Type`.

    The Type cell is not a column on `curated_entry`; it is read back out of `raw_cells`. Without that
    leg a blank `Unit` parses as a film, and every one of those rows would resolve to the wrong kind.
    """
    category = await seeded_category(db_session, "retry-blank-unit")
    entry = await seeded_entry(
        db_session,
        category,
        position=1,
        raw_title=ONE_PIECE,
        raw_unit="",
        raw_release=A_RELEASE_YEAR,
        raw_type=AN_EPISODIC_TYPE_CELL,
        note=A_STALE_NOTE,
    )

    response = await client.post(RETRY_PATH.format(entry_id=entry.id))

    assert response.status_code == 200
    body = response.json()
    assert body["unit_kind"] == UnitKind.SERIES.value
    assert body["title"]["tmdb_id"] == ONE_PIECE_TMDB_ID


async def test_busy_numbering_is_409_and_request_cleanup_rolls_back_every_prior_retry_write(
    engine: AsyncEngine, settings: Settings, catalog: Catalog
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        title = await seeded_title(seed, name="Before provider refresh", tmdb_id=ONE_PIECE_TMDB_ID)
        entry = await _an_unresolved_one_piece_row(seed, f"retry-busy-{uuid.uuid4()}")
        category_id = entry.category_id
        before = _full_state(entry)
        await seed.commit()
    configured = settings.model_copy(
        update={"tvdb_api_key": SecretStr(A_RECORDED_KEY), "tvdb_pin": SecretStr(A_RECORDED_PIN)}
    )
    runtime = tmdb_runtime(configured, catalog, engine, *_one_piece_answers())
    try:
        async with AsyncSession(engine) as playback:
            assert await try_episode_order_locks(playback, [title.id], shared=True)
            async with AsyncSession(engine) as request_session:
                async with _wired(catalog, settings, request_session, runtime) as client:
                    response = await client.post(RETRY_PATH.format(entry_id=entry.id))
                assert response.status_code == 409
                assert response.json()["error"] == "ResolutionConflictError"
                assert "numbering is busy" in response.json()["detail"]
                assert await request_session.scalar(select(Title.name).where(Title.id == title.id)) == ONE_PIECE
            async with AsyncSession(engine) as check:
                assert await check.scalar(select(Title.name).where(Title.id == title.id)) == "Before provider refresh"
                assert _full_state(await _reread(check, entry.id)) == before
    finally:
        await runtime.aclose()
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.id == entry.id))
            await cleanup.execute(delete(Category).where(Category.id == category_id))
            await cleanup.execute(delete(Title).where(Title.id == title.id))
            await cleanup.commit()
