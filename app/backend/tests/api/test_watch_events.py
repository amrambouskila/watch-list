"""`POST /api/watch-events` and the derived-state read, through the real application.

The log is the durable half of "progress is written to both" (CLAUDE.md section 0.2), so the passes
that matter here write a real `.xlsx`: the response is sent, the scheduled mirror runs, and the sheet
cell the owner sees in Excel says what the view derived. Those need a real Postgres and skip loudly
without one; the route's own contract - the OpenAPI document, the envelopes, the boundary refusals -
needs none.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from database_support import JoiningSessionFactory
from library_choice import a_category
from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.constants import UNWATCHED, WATCHED
from tv_watchlist.data.enums import MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, Episode, Season, Title
from tv_watchlist.data.session import get_session, get_session_factory
from tv_watchlist.main import create_app
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.schema import watch_column
from workbook_facts import WorkbookFacts

EVENTS_PATH: Final[str] = "/api/watch-events"
PROGRESS_PATH: Final[str] = "/api/categories/{category_id}/entries/{entry_id}/progress"
CREATED: Final[int] = 201
UNPROCESSABLE: Final[int] = 422
NOT_FOUND: Final[int] = 404
AN_ACCENT: Final[str] = "#1F2937"
ONE_PIECE_TMDB_ID: Final[int] = 37854
LABOON_SEASON: Final[int] = 2
LABOON_EPISODE: Final[int] = 62
LABOON_KEY: Final[str] = "tv:37854:s2:e62"
A_STAMP: Final[datetime] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _wired(catalog: Catalog, settings: Settings, session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_session_factory] = JoiningSessionFactory(session)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def offline_client(catalog: Catalog, settings: Settings) -> AsyncIterator[AsyncClient]:
    """No database: the session is unbound, so anything reaching it fails loudly rather than quietly."""
    async with _wired(catalog, settings, AsyncSession()) as client:
        yield client


@pytest.fixture
async def client(catalog: Catalog, settings: Settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async with _wired(catalog, settings, db_session) as client:
        yield client


class _Projected:
    """One real workbook, ingested once: a category row, one entry, and the sheet row it came from."""

    def __init__(self, path: Path, category: Category, entry: CuratedEntry, watch_key: str) -> None:
        self.path = path
        self.category = category
        self.entry = entry
        self.watch_key = watch_key

    def cell(self) -> str:
        """That entry's status cell as the sheet now reads it."""
        rows = {row.row: row.cells for row in read_category(self.path).rows}
        assert self.entry.sheet_row is not None
        return rows[self.entry.sheet_row].get(self.watch_key, UNWATCHED).strip()


async def _projected(session: AsyncSession, library: Path, subject: WorkbookFacts) -> _Projected:
    path = subject.copied_into(library)
    detail = read_category(path)
    column = watch_column(detail.columns)
    assert column is not None
    category = Category(
        slug=detail.id,
        file_name=detail.file_name,
        sheet_title=detail.sheet_title,
        accent=detail.accent,
        workbook_mtime=detail.mtime,
    )
    session.add(category)
    await session.flush()
    first = detail.rows[0]
    entry = CuratedEntry(
        category_id=category.id,
        position=1,
        sheet_row=first.row,
        unit_kind=UnitKind.UNKNOWN,
        resolution_state=ResolutionState.UNRESOLVED,
        raw_cells=first.cells,
        raw_title=first.cells.get(subject.title_key, ""),
        mirrored_watch_cell=UNWATCHED,
        observed_watch_cell=UNWATCHED,
    )
    session.add(entry)
    await session.flush()
    return _Projected(path, category, entry, column.key)


@pytest.fixture
async def projected(db_session: AsyncSession, library: Path, subject: WorkbookFacts) -> _Projected:
    return await _projected(db_session, library, subject)


async def _laboon(session: AsyncSession, projected: _Projected) -> Episode:
    """One episode of a resolved series, flattened into that entry's queue slot."""
    title = Title(media_type=MediaType.TV, name="One Piece", match_key="one piece", tmdb_id=ONE_PIECE_TMDB_ID)
    session.add(title)
    await session.flush()
    season = Season(title_id=title.id, season_number=LABOON_SEASON)
    session.add(season)
    await session.flush()
    episode = Episode(
        title_id=title.id,
        season_id=season.id,
        season_number=LABOON_SEASON,
        episode_number=LABOON_EPISODE,
        tmdb_episode_id=1,
    )
    session.add(episode)
    await session.flush()
    session.add(
        CuratedEntryItem(
            category_id=projected.category.id,
            curated_entry_id=projected.entry.id,
            episode_id=episode.id,
            position_in_entry=1,
            absolute_position=1,
        )
    )
    await session.flush()
    return episode


def _body(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401  # a request payload is heterogeneous
    payload: dict[str, Any] = {
        "subject_kind": "curated_entry",
        "subject_id": str(uuid.uuid4()),
        "kind": "completed",
    }
    payload.update(overrides)
    return payload


# -- the contract, with no database ------------------------------------------------------------------


def test_both_routes_are_in_the_applications_openapi_document() -> None:
    paths = create_app().openapi()["paths"]

    assert "post" in paths[EVENTS_PATH]
    assert "get" in paths[PROGRESS_PATH]
    assert "201" in paths[EVENTS_PATH]["post"]["responses"]


def test_the_response_schema_is_the_watch_event_read_contract() -> None:
    schemas = create_app().openapi()["components"]["schemas"]

    assert "WatchEventRead" in schemas
    assert "progress" in schemas["WatchEventRead"]["properties"]


@pytest.mark.parametrize(
    "body",
    [
        _body(kind="progressed"),
        _body(kind="progressed", position_seconds=12.5),
        _body(source="ui"),
        _body(tmdb_key=LABOON_KEY),
        _body(subject_id="not-a-uuid"),
        _body(subject_kind="sheet_row"),
        _body(position_seconds=-1),
    ],
    ids=[
        "progressed-without-position",
        "float-position",
        "source-is-the-servers",
        "tmdb-key-is-the-servers",
        "subject-not-a-uuid",
        "unknown-subject-kind",
        "negative-position",
    ],
)
async def test_a_body_the_contract_refuses_never_reaches_the_database(
    offline_client: AsyncClient, body: dict[str, Any]
) -> None:
    """Every one of these is refused by the model, so the unbound session is never touched."""
    response = await offline_client.post(EVENTS_PATH, json=body)

    assert response.status_code == UNPROCESSABLE


# -- recording, with a real database and a real workbook ----------------------------------------------


async def test_recording_against_an_entry_returns_201_and_its_derived_progress(
    client: AsyncClient, projected: _Projected
) -> None:
    response = await client.post(EVENTS_PATH, json=_body(subject_id=str(projected.entry.id)))

    assert response.status_code == CREATED
    body = response.json()
    assert body["subject_kind"] == "curated_entry"
    assert body["source"] == "ui"
    assert body["curated_entry_id"] == str(projected.entry.id)
    assert body["progress"]["kind"] == "completed"
    assert body["recorded_at"]


async def test_a_completed_episode_event_returns_the_span_progress_not_the_request(
    client: AsyncClient, db_session: AsyncSession, projected: _Projected
) -> None:
    episode = await _laboon(db_session, projected)

    body = (await client.post(EVENTS_PATH, json=_body(subject_kind="episode", subject_id=str(episode.id)))).json()

    # One of one episode completed reads as completed; the entry it moved travels with it.
    assert body["progress"]["episode_total"] == 1
    assert body["progress"]["episode_completed"] == 1
    assert body["curated_entry_id"] == str(projected.entry.id)


async def test_the_tmdb_key_is_derived_server_side_never_from_the_body(
    client: AsyncClient, db_session: AsyncSession, projected: _Projected
) -> None:
    """The reference value: TMDB buckets One Piece absolutely, so Laboon is s2e62 (section 11.2, rule 9)."""
    episode = await _laboon(db_session, projected)

    body = (await client.post(EVENTS_PATH, json=_body(subject_kind="episode", subject_id=str(episode.id)))).json()

    assert body["tmdb_key"] == LABOON_KEY


async def test_an_unknown_subject_is_404_with_its_own_error_code(client: AsyncClient) -> None:
    missing = uuid.uuid4()

    response = await client.post(EVENTS_PATH, json=_body(subject_id=str(missing)))

    assert response.status_code == NOT_FOUND
    body = response.json()
    assert body["error"] == "WatchSubjectNotFoundError"
    assert str(missing) in body["detail"]
    assert body["message"] == f"No curated_entry {missing} to record a watch event against."


async def test_a_late_client_stamp_is_kept_and_recorded_at_is_the_servers(
    client: AsyncClient, projected: _Projected
) -> None:
    body = (
        await client.post(EVENTS_PATH, json=_body(subject_id=str(projected.entry.id), occurred_at=A_STAMP.isoformat()))
    ).json()

    assert datetime.fromisoformat(body["occurred_at"]) == A_STAMP
    assert datetime.fromisoformat(body["recorded_at"]) > A_STAMP


# -- the scheduled mirror ------------------------------------------------------------------------------


async def test_recording_a_completion_schedules_the_mirror_and_the_sheet_cell_reads_watched(
    client: AsyncClient, projected: _Projected
) -> None:
    """The other half of "progress is written to both": the owner sees it in Excel (section 0.2)."""
    assert projected.cell() == UNWATCHED

    response = await client.post(EVENTS_PATH, json=_body(subject_id=str(projected.entry.id)))

    assert response.status_code == CREATED
    assert projected.cell() == WATCHED
    # Remembered, so the next ingest reads our own echo rather than a hand edit (section 5.16).
    assert projected.entry.mirrored_watch_cell == WATCHED


async def test_an_event_no_curated_row_covers_leaves_every_workbook_alone(
    client: AsyncClient, db_session: AsyncSession, projected: _Projected
) -> None:
    """Nothing to mirror means nothing is opened, so no snapshot is taken and no stamp moves."""
    title = Title(media_type=MediaType.TV, name="Unheld", match_key="unheld", tmdb_id=1)
    db_session.add(title)
    await db_session.flush()
    before = projected.path.stat().st_mtime

    body = (await client.post(EVENTS_PATH, json=_body(subject_kind="title", subject_id=str(title.id)))).json()

    assert body["curated_entry_id"] is None
    assert body["progress"] is None
    assert projected.path.stat().st_mtime == before


# -- the derived read ----------------------------------------------------------------------------------


async def test_the_derived_read_matches_the_post_response(client: AsyncClient, projected: _Projected) -> None:
    written = (await client.post(EVENTS_PATH, json=_body(subject_id=str(projected.entry.id)))).json()

    response = await client.get(PROGRESS_PATH.format(category_id=projected.category.slug, entry_id=projected.entry.id))

    assert response.status_code == 200
    assert response.json() == written["progress"]


async def test_the_derived_read_is_404_for_an_id_no_live_entry_answers_to(
    client: AsyncClient, projected: _Projected
) -> None:
    missing = uuid.uuid4()

    response = await client.get(PROGRESS_PATH.format(category_id=projected.category.slug, entry_id=missing))

    assert response.status_code == NOT_FOUND
    assert response.json()["error"] == "EntryNotFoundError"


async def test_the_derived_read_will_not_answer_for_another_categorys_entry(
    client: AsyncClient, projected: _Projected
) -> None:
    """The path names a category, so it must mean it."""
    other = a_category().category_id

    response = await client.get(PROGRESS_PATH.format(category_id=f"{other}-not-this-one", entry_id=projected.entry.id))

    assert response.status_code == NOT_FOUND
