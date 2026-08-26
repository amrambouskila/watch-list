"""The retire endpoint: it answers with the library that is left, and refuses rather than half-moves."""

from __future__ import annotations

from collections.abc import AsyncIterator
from http import HTTPStatus
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from retirement_files import retirements
from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.config import Settings
from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.locking import excel_lock_path
from workbook_facts import WorkbookFacts

UNKNOWN_ID = "no-category-answers-to-this"
# Far enough from any real mtime that no filesystem granularity could make it look current.
A_STAMP_THE_WORKBOOK_NEVER_HAD = 1_000_000.0


@pytest.fixture
async def client(catalog: Catalog) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def retire(client: AsyncClient, category_id: str, expected_mtime: float) -> tuple[int, dict[str, object]]:
    response = await client.delete(f"/api/categories/{category_id}", params={"expected_mtime": expected_mtime})
    return response.status_code, response.json()


async def test_retiring_a_category_answers_with_the_library_that_is_left(
    client: AsyncClient, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    detail = (await client.get(f"/api/categories/{subject.category_id}")).json()

    status, body = await retire(client, subject.category_id, detail["mtime"])

    assert status == HTTPStatus.OK
    assert subject.category_id not in {category["id"] for category in body["categories"]}
    assert not subject_path.exists()
    assert len(retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)) == 1
    listing = (await client.get("/api/categories")).json()
    assert subject.category_id not in {category["id"] for category in listing["categories"]}


async def test_retiring_an_unknown_category_is_a_404(client: AsyncClient) -> None:
    status, body = await retire(client, UNKNOWN_ID, A_STAMP_THE_WORKBOOK_NEVER_HAD)

    assert status == HTTPStatus.NOT_FOUND
    assert body["error"] == "CategoryNotFoundError"


async def test_retiring_a_workbook_open_in_excel_is_refused_and_it_stays_put(
    client: AsyncClient, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    detail = (await client.get(f"/api/categories/{subject.category_id}")).json()
    excel_lock_path(subject_path).write_bytes(b"owner")

    status, body = await retire(client, subject.category_id, detail["mtime"])

    assert status == HTTPStatus.LOCKED
    assert body["error"] == "WorkbookLockedError"
    assert subject_path.is_file()
    assert retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX) == []


async def test_retiring_against_a_stale_stamp_is_refused_and_it_stays_put(
    client: AsyncClient, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    status, body = await retire(client, subject.category_id, A_STAMP_THE_WORKBOOK_NEVER_HAD)

    assert status == HTTPStatus.CONFLICT
    assert body["error"] == "StaleWorkbookError"
    assert subject_path.is_file()
    assert retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX) == []
