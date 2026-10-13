from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from mirror_support import moved_on
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database_support import JoiningSessionFactory
from playback_projection import PlaybackProjection
from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import WatchEventKind
from tv_watchlist.data.models import PlaybackCompletion, PlaybackCompletionEvent, WatchEvent
from tv_watchlist.data.session import get_session, get_session_factory
from tv_watchlist.main import create_app
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.watch_event_read import WatchEventRead
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.locking import excel_lock_path


@pytest.fixture
async def client(db_session: AsyncSession, catalog: Catalog) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_session_factory] = JoiningSessionFactory(db_session)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        yield client


async def test_event_then_projection_uses_the_exact_contract_and_no_background_workbook_write(
    db_session: AsyncSession,
    catalog: Catalog,
    subject_path: Path,
    client: AsyncClient,
) -> None:
    projected = await PlaybackProjection.create(db_session, catalog, subject_path)
    entry = projected.entries[1]
    untouched = subject_path.read_bytes()
    response = await client.post(
        "/api/watch-events",
        params={"playback_entry_id": str(entry.id), "jellyfin_item_id": str(projected.file.id)},
        json=projected.snapshot().model_dump(mode="json"),
    )
    assert response.status_code == 201
    event = response.json()
    assert event["source"] == "player" and event["curated_entry_id"] == str(entry.id)
    assert subject_path.read_bytes() == untouched
    response = await client.post(
        f"/api/playback/entries/{entry.id}/position",
        json={"watch_event_id": event["id"], "expected_mtime": projected.category.workbook_mtime},
    )
    assert response.status_code == 200
    detail = CategoryDetail.model_validate(response.json())
    assert set(response.json()) == set(CategoryDetail.model_fields)
    assert all(column.role not in {"identity", "position"} for column in detail.columns)
    assert projected.cell(entry) == "In progress"
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 1


@pytest.mark.parametrize("refusal", ["locked", "stale"])
@pytest.mark.parametrize("completed", [False, True])
async def test_workbook_errors_do_not_undo_the_committed_event_or_duplicate_it_on_retry(
    db_session: AsyncSession,
    catalog: Catalog,
    subject_path: Path,
    client: AsyncClient,
    refusal: str,
    completed: bool,
) -> None:
    projected = await PlaybackProjection.create(db_session, catalog, subject_path)
    entry = projected.entries[1]
    response = await client.post(
        "/api/watch-events",
        params={"playback_entry_id": str(entry.id), "jellyfin_item_id": str(projected.file.id)},
        json=projected.snapshot(
            seconds=300 if completed else 60,
            kind=WatchEventKind.COMPLETED if completed else WatchEventKind.PROGRESSED,
        ).model_dump(mode="json"),
    )
    assert response.status_code == 201
    receipts_before = list(await db_session.scalars(select(PlaybackCompletion.id)))
    assert set(response.json()) == set(WatchEventRead.model_fields)
    assert len(receipts_before) == int(completed)
    if completed:
        receipt = await db_session.scalar(select(PlaybackCompletion))
        assert receipt is not None and str(receipt.selected_watch_event_id) == response.json()["id"]
    payload = {"watch_event_id": response.json()["id"], "expected_mtime": projected.category.workbook_mtime}
    if refusal == "locked":
        excel_lock_path(subject_path).write_bytes(b"owner")
    else:
        moved_on(subject_path)
    first = await client.post(f"/api/playback/entries/{entry.id}/position", json=payload)
    assert first.status_code == (423 if refusal == "locked" else 409)
    assert first.json()["error"] == ("WorkbookLockedError" if refusal == "locked" else "StaleWorkbookError")
    if refusal == "locked":
        excel_lock_path(subject_path).unlink()
    second = await client.post(f"/api/playback/entries/{entry.id}/position", json=payload)
    assert second.status_code == (200 if refusal == "locked" else 409)
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == (3 if completed else 1)
    assert list(await db_session.scalars(select(PlaybackCompletion.id))) == receipts_before
    assert await db_session.scalar(select(func.count()).select_from(PlaybackCompletionEvent)) == (3 if completed else 0)


@pytest.mark.parametrize("single", ["playback_entry_id", "jellyfin_item_id"])
async def test_player_query_context_is_an_indivisible_pair(client: AsyncClient, single: str) -> None:
    response = await client.post(
        "/api/watch-events",
        params={single: str(uuid.uuid4())},
        json={"subject_kind": "title", "subject_id": str(uuid.uuid4()), "kind": "progressed", "position_seconds": 1},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["unknown", "removed", "retired"])
async def test_player_routes_refuse_missing_live_entries(
    db_session: AsyncSession,
    catalog: Catalog,
    subject_path: Path,
    client: AsyncClient,
    missing: str,
) -> None:
    projected = await PlaybackProjection.create(db_session, catalog, subject_path)
    entry = projected.entries[1]
    if missing == "removed":
        entry.removed_at = utcnow()
    if missing == "retired":
        projected.category.retired_at = utcnow()
    await db_session.flush()
    entry_id = uuid.uuid4() if missing == "unknown" else entry.id
    event = await client.post(
        "/api/watch-events",
        params={"playback_entry_id": str(entry_id), "jellyfin_item_id": str(projected.file.id)},
        json=projected.snapshot().model_dump(mode="json"),
    )
    projection = await client.post(
        f"/api/playback/entries/{entry_id}/position", json={"watch_event_id": str(uuid.uuid4()), "expected_mtime": 0}
    )
    assert event.status_code == projection.status_code == 404
    assert event.json()["error"] == projection.json()["error"] == "EntryNotFoundError"


async def test_invalid_player_state_returns_a_typed_conflict(
    db_session: AsyncSession,
    catalog: Catalog,
    subject_path: Path,
    client: AsyncClient,
) -> None:
    projected = await PlaybackProjection.create(db_session, catalog, subject_path)
    entry = projected.entries[1]
    event = await client.post(
        "/api/watch-events",
        params={"playback_entry_id": str(entry.id), "jellyfin_item_id": str(uuid.uuid4())},
        json=projected.snapshot().model_dump(mode="json"),
    )
    projection = await client.post(
        f"/api/playback/entries/{entry.id}/position", json={"watch_event_id": str(uuid.uuid4()), "expected_mtime": 0}
    )
    assert event.status_code == projection.status_code == 409
    assert event.json()["error"] == projection.json()["error"] == "PlaybackStateError"


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("overflow", ["position_seconds", "runtime_seconds"])
async def test_player_integer_overflow_is_a_conflict_before_any_range_event_insert(
    db_session: AsyncSession,
    catalog: Catalog,
    subject_path: Path,
    client: AsyncClient,
    completed: bool,
    overflow: str,
) -> None:
    projected = await PlaybackProjection.create(db_session, catalog, subject_path)
    entry = projected.entries[1]
    body = projected.snapshot(
        seconds=300,
        kind=WatchEventKind.COMPLETED if completed else WatchEventKind.PROGRESSED,
    ).model_dump(mode="json")
    body[overflow] = 2_147_483_648
    response = await client.post(
        "/api/watch-events",
        params={"playback_entry_id": str(entry.id), "jellyfin_item_id": str(projected.file.id)},
        json=body,
    )
    assert response.status_code == 409
    assert response.json()["error"] == "PlaybackStateError"
    assert "storage range" in response.json()["message"]
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == 0


@pytest.mark.parametrize("completed", [False, True])
async def test_the_postgresql_integer_boundary_is_supported_for_progress_and_range_completion(
    db_session: AsyncSession,
    catalog: Catalog,
    subject_path: Path,
    client: AsyncClient,
    completed: bool,
) -> None:
    projected = await PlaybackProjection.create(db_session, catalog, subject_path)
    entry = projected.entries[1]
    body = projected.snapshot(
        seconds=2_147_483_647,
        kind=WatchEventKind.COMPLETED if completed else WatchEventKind.PROGRESSED,
    ).model_dump(mode="json")
    body["runtime_seconds"] = 2_147_483_647 if completed else None
    response = await client.post(
        "/api/watch-events",
        params={"playback_entry_id": str(entry.id), "jellyfin_item_id": str(projected.file.id)},
        json=body,
    )
    assert response.status_code == 201
    assert response.json()["position_seconds"] == 2_147_483_647
    assert await db_session.scalar(select(func.count()).select_from(WatchEvent)) == (3 if completed else 1)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"watch_event_id": "no", "expected_mtime": 1},
        {"watch_event_id": str(uuid.uuid4()), "expected_mtime": 1, "position_seconds": 5},
        {"watch_event_id": str(uuid.uuid4()), "expected_mtime": 1, "row": 3},
    ],
)
async def test_position_endpoint_takes_only_an_event_uuid_and_stamp(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post(f"/api/playback/entries/{uuid.uuid4()}/position", json=payload)
    assert response.status_code == 422
