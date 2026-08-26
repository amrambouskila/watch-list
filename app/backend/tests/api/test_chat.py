"""The chat transport: session lifecycle, the SSE frame stream, and the approve write."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import NamedTuple

import httpx
import pytest
from claude_agent_sdk import CLINotFoundError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from mock_responder import MockResponder
from recording_reader import RecordingReader
from sample_images import PNG
from stub_client import StubClient

from library_choice import a_category, a_name_the_library_does_not_hold
from tv_watchlist.agent.constants import (
    QUALIFIED_FETCH_URL_TOOL,
    QUALIFIED_GET_CATEGORY_TOOL,
    TOOL_STATE_RUNNING,
)
from tv_watchlist.agent.dependencies import get_agent_runtime
from tv_watchlist.agent.errors import UnknownProposalError, UnknownSessionError
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.registry import SessionRegistry
from tv_watchlist.agent.runtime import AgentRuntime
from tv_watchlist.agent.session import ChatSession
from tv_watchlist.agent.tool_result import ToolResult
from tv_watchlist.agent.tools.get_category import build_get_category_tool
from tv_watchlist.agent.tools.propose import build_propose_tool
from tv_watchlist.api.dependencies import get_catalog, get_hero_store
from tv_watchlist.config import Settings, get_settings
from tv_watchlist.constants import FIRST_DATA_ROW, HERO_ATTRIBUTION_FILENAME, MAX_CHAT_MESSAGE_LENGTH
from tv_watchlist.main import create_app
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.chat_event import ChatEvent
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.hero_store import HeroStore
from tv_watchlist.workbook.locking import excel_lock_path

ToolHandler = Callable[[dict[str, object]], Awaitable[ToolResult]]

SESSION_ID = "session-1"
PROPOSAL_ID = "proposal-1"
# Whichever category the library offers first by shape; the chat layer only ever sees its id.
CATEGORY = a_category()
WATCH_KEY = CATEGORY.watch_key
TITLE_KEY = CATEGORY.title_key
# An explicit, clearly different timestamp: Windows mtime granularity is far too coarse to trust a
# rewrite landing on a new tick.
EDITED_MTIME = 1_000_000.0
EDIT_SUMMARY = "mark the opening episode watched"
EDIT_CHANGES = [{"kind": "revise", "row": FIRST_DATA_ROW, "cells": {WATCH_KEY: "Watched"}}]
EDIT_BODY = {"kind": "edit", "category_id": CATEGORY.category_id, "changes": EDIT_CHANGES}
HERO_SUMMARY = "three logo marks for the card"
FIRST_CANDIDATE_FILE = "Series logo.png"
SECOND_CANDIDATE_FILE = "Series wordmark.png"
HERO_CANDIDATES = [
    {
        "url": "https://93.184.216.34/wikipedia/commons/9/97/Series_logo.png",
        "source_file": FIRST_CANDIDATE_FILE,
        "licence": "Public domain",
        "page": "https://commons.wikimedia.org/wiki/File:Series_logo.png",
        "description": "The series logotype on transparency.",
    },
    {
        "url": "https://93.184.216.34/wikipedia/commons/1/13/Series_wordmark.png",
        "source_file": SECOND_CANDIDATE_FILE,
        "licence": "CC0",
        "page": "https://commons.wikimedia.org/wiki/File:Series_wordmark.png",
        "description": "The stylised wordmark.",
    },
]
HERO_BODY = {"kind": "hero", "category_id": CATEGORY.category_id, "candidates": HERO_CANDIDATES}
# Far enough down the sheet that deleting the first data row puts a different title here.
SHIFTED_ROW = 5
REQUEST = "build me a chronological wartime list"
SEARCH_NOTE = "Searching for chronological wartime film lists."
BUILT_CATEGORY_NAME = a_name_the_library_does_not_hold("Wartime Films")
BUILT_CATEGORY_STEM = "Wartime_Films"
BUILT_TITLE = "Dunkirk"
FRAME_SEPARATOR = "\n\n"
DATA_PREFIX = "data: "
TURN = [
    ChatEvent(type="text", text=SEARCH_NOTE),
    ChatEvent(type="tool", name=QUALIFIED_FETCH_URL_TOOL, detail="reddit.com/r/movies", state=TOOL_STATE_RUNNING),
    ChatEvent(type="done", turns=7, total_cost_usd=0.14),
]


def category_mtime(library: Path) -> float:
    """The workbook's freshness stamp, as the write guard reads it."""
    return CATEGORY.copied_into(library).stat().st_mtime


def an_edit_body(row: int) -> dict[str, object]:
    """The same researched change, aimed at whichever row the test cares about."""
    return {**EDIT_BODY, "changes": [{**EDIT_CHANGES[0], "row": row}]}


def cell_at(detail: CategoryDetail, row: int, key: str) -> str:
    """One cell of one row number, as the sheet currently stands."""
    return next(found.cells.get(key, "") for found in detail.rows if found.row == row)


def an_edit_proposal(read_mtime: float) -> Proposal:
    """A pending edit, stamped with the mtime its row numbers were resolved against."""
    return Proposal(
        id=PROPOSAL_ID,
        summary=EDIT_SUMMARY,
        sources=["https://example.com"],
        body={**EDIT_BODY, "read_mtime": read_mtime},
    )


async def a_researched_edit(catalog: Catalog, row: int = FIRST_DATA_ROW) -> Proposal:
    """What a session's own tools produce: a read, then a proposal stamped with what that read saw."""
    recorded: list[Proposal] = []

    async def record(proposal: Proposal) -> None:
        recorded.append(proposal)

    read_log = ReadLog()
    await build_get_category_tool(catalog, read_log).handler({"category_id": CATEGORY.category_id})
    await build_propose_tool(record, read_log).handler({"summary": EDIT_SUMMARY, "body": an_edit_body(row)})
    return recorded[0]


class Researcher(NamedTuple):
    """One live session, its registry, and the real library tools bound to its read log."""

    sessions: SessionRegistry
    session: ChatSession
    read: ToolHandler
    propose: ToolHandler


async def a_researcher(catalog: Catalog) -> Researcher:
    """The real composition root driving one real session, minus the CLI subprocess and the network."""
    fetcher = Fetcher(RecordingReader(), transport=MockResponder(Response(200)).transport)
    runtime = AgentRuntime(catalog, fetcher, client_factory=StubClient)
    session = await runtime.sessions.create()
    return Researcher(
        runtime.sessions,
        session,
        build_get_category_tool(catalog, session.read_log).handler,
        build_propose_tool(session.record_proposal, session.read_log).handler,
    )


async def an_approved_edit(client: AsyncClient, research: Researcher, row: int) -> Response:
    """Propose one researched edit on a session's own tools, then approve it through the API."""
    await research.propose({"summary": EDIT_SUMMARY, "body": an_edit_body(row)})
    proposal = research.session.pending_proposal
    assert proposal is not None
    return await client.post(f"/api/chat/proposals/{proposal.id}/approve")


def frames_of(response: Response) -> list[dict[str, object]]:
    """Every `data:` line of an SSE body, parsed back into a frame."""
    blocks = [block for block in response.text.split(FRAME_SEPARATOR) if block]
    return [json.loads(block.removeprefix(DATA_PREFIX)) for block in blocks]


class StubSession:
    """A chat session stand-in: no CLI, no model, just the frames the test scripted."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.script: list[ChatEvent] = []
        self.prompts: list[str] = []

    async def send(self, text: str) -> AsyncIterator[ChatEvent]:
        self.prompts.append(text)
        for event in self.script:
            yield event


class StubSessions:
    """The session-registry surface the chat router actually uses."""

    def __init__(self) -> None:
        self.session = StubSession(SESSION_ID)
        self.create_failure: Exception | None = None
        self.closed: list[str] = []
        self.pending: Proposal | None = None
        self.written: list[str] = []

    async def create(self) -> StubSession:
        if self.create_failure is not None:
            raise self.create_failure
        return self.session

    async def get(self, session_id: str) -> StubSession:
        if session_id != self.session.id:
            raise UnknownSessionError(session_id)
        return self.session

    async def close(self, session_id: str) -> None:
        if session_id != self.session.id:
            raise UnknownSessionError(session_id)
        self.closed.append(session_id)

    def proposal(self, proposal_id: str) -> Proposal:
        if self.pending is None or self.pending.id != proposal_id:
            raise UnknownProposalError(proposal_id)
        return self.pending

    def applied(self, proposal_id: str) -> None:
        self.written.append(proposal_id)


class StubRuntime:
    """The agent runtime as the chat router sees it: a registry and nothing else."""

    def __init__(self, sessions: StubSessions | SessionRegistry) -> None:
        self.sessions = sessions
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def run_lifespan(app: FastAPI) -> None:
    """Take an app through startup and shutdown the way the ASGI server does."""
    events: list[dict[str, str]] = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

    async def receive() -> dict[str, str]:
        return events.pop(0)

    async def send(message: dict[str, str]) -> None:
        return None

    await app({"type": "lifespan"}, receive, send)


def client_for(
    catalog: Catalog, sessions: StubSessions | SessionRegistry, hero_store: HeroStore | None = None
) -> AsyncClient:
    """An HTTP client on a fresh app bound to one catalog and one stub registry."""
    app = create_app()
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_agent_runtime] = lambda: StubRuntime(sessions)
    if hero_store is not None:
        app.dependency_overrides[get_hero_store] = lambda: hero_store
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def sessions() -> StubSessions:
    return StubSessions()


@pytest.fixture
def hero_store(catalog: Catalog, settings: Settings) -> HeroStore:
    """A store that writes into the throwaway heroes folder and answers downloads from canned bytes."""
    return HeroStore(catalog, settings, transport=MockResponder(httpx.Response(200, content=PNG)).transport)


@pytest.fixture
async def client(catalog: Catalog, sessions: StubSessions, hero_store: HeroStore) -> AsyncIterator[AsyncClient]:
    async with client_for(catalog, sessions, hero_store) as async_client:
        yield async_client


async def test_creating_a_session_returns_its_id(client: AsyncClient) -> None:
    response = await client.post("/api/chat/sessions")

    assert response.status_code == 200
    assert response.json() == {"session_id": SESSION_ID}


async def test_a_missing_claude_cli_is_a_503_rather_than_a_crash(client: AsyncClient, sessions: StubSessions) -> None:
    sessions.create_failure = CLINotFoundError()

    response = await client.post("/api/chat/sessions")

    assert response.status_code == 503
    assert response.json()["error"] == "CLINotFoundError"
    assert "PATH" in response.json()["message"]


async def test_a_turn_streams_one_json_frame_per_event(client: AsyncClient, sessions: StubSessions) -> None:
    sessions.session.script = TURN

    response = await client.post(f"/api/chat/sessions/{SESSION_ID}/messages", json={"text": REQUEST})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert sessions.session.prompts == [REQUEST]
    frames = frames_of(response)
    assert frames == [
        {"type": "text", "text": SEARCH_NOTE},
        {
            "type": "tool",
            "name": QUALIFIED_FETCH_URL_TOOL,
            "detail": "reddit.com/r/movies",
            "state": TOOL_STATE_RUNNING,
        },
        {"type": "done", "turns": 7, "total_cost_usd": 0.14},
    ]


async def test_the_stream_carries_the_headers_a_buffering_proxy_would_need(
    client: AsyncClient, sessions: StubSessions
) -> None:
    sessions.session.script = TURN

    response = await client.post(f"/api/chat/sessions/{SESSION_ID}/messages", json={"text": REQUEST})

    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


async def test_a_message_to_a_session_that_has_gone_is_a_404(client: AsyncClient) -> None:
    response = await client.post("/api/chat/sessions/expired/messages", json={"text": REQUEST})

    assert response.status_code == 404
    assert response.json()["error"] == "UnknownSessionError"
    assert "expired" in response.json()["message"]


async def test_closing_a_session_ends_it_and_answers_no_content(client: AsyncClient, sessions: StubSessions) -> None:
    response = await client.delete(f"/api/chat/sessions/{SESSION_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert sessions.closed == [SESSION_ID]


async def test_approving_an_edit_writes_it_through_the_catalog(
    client: AsyncClient, sessions: StubSessions, library: Path
) -> None:
    sessions.pending = an_edit_proposal(category_mtime(library))

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/approve")

    assert response.status_code == 200
    assert response.json()["rows"][0]["cells"][WATCH_KEY] == "Watched"
    assert sessions.written == [PROPOSAL_ID]


async def test_approving_a_proposal_no_session_still_holds_is_a_404(client: AsyncClient) -> None:
    response = await client.post("/api/chat/proposals/forgotten/approve")

    assert response.status_code == 404
    assert response.json()["error"] == "UnknownProposalError"
    assert "forgotten" in response.json()["message"]


async def test_approving_into_a_workbook_open_in_excel_is_a_409_that_keeps_the_proposal(
    client: AsyncClient, sessions: StubSessions, library: Path
) -> None:
    sessions.pending = an_edit_proposal(category_mtime(library))
    excel_lock_path(CATEGORY.copied_into(library)).write_bytes(b"owner")

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/approve")

    assert response.status_code == 409
    assert response.json()["error"] == "WorkbookLockedError"
    assert "open in Excel" in response.json()["message"]
    assert sessions.written == []


async def test_a_workbook_edited_after_claude_read_it_is_a_409_that_keeps_the_proposal(
    client: AsyncClient, catalog: Catalog, sessions: StubSessions, library: Path
) -> None:
    proposal = await a_researched_edit(catalog)
    sessions.pending = proposal
    os.utime(CATEGORY.copied_into(library), (EDITED_MTIME, EDITED_MTIME))

    response = await client.post(f"/api/chat/proposals/{proposal.id}/approve")

    assert response.status_code == 409
    assert response.json()["error"] == "StaleWorkbookError"
    assert "changed on disk" in response.json()["message"]
    assert sessions.written == []
    assert sessions.proposal(proposal.id) is proposal


async def test_a_row_the_user_deleted_meanwhile_never_lets_the_edit_land_on_the_title_beneath_it(
    client: AsyncClient, catalog: Catalog, sessions: StubSessions
) -> None:
    read = await catalog.detail(CATEGORY.category_id)
    proposal = await a_researched_edit(catalog, SHIFTED_ROW)
    sessions.pending = proposal
    deleted = await client.delete(
        f"/api/categories/{CATEGORY.category_id}/rows/{FIRST_DATA_ROW}", params={"expected_mtime": read.mtime}
    )
    assert deleted.status_code == 200
    shifted = await catalog.detail(CATEGORY.category_id)
    # The row number Claude researched now names a different episode, which is the corruption.
    assert cell_at(read, SHIFTED_ROW, TITLE_KEY) != cell_at(shifted, SHIFTED_ROW, TITLE_KEY)

    response = await client.post(f"/api/chat/proposals/{proposal.id}/approve")

    assert response.status_code == 409
    assert response.json()["error"] == "StaleWorkbookError"
    assert cell_at(await catalog.detail(CATEGORY.category_id), SHIFTED_ROW, WATCH_KEY) != "Watched"
    assert sessions.written == []


async def test_the_kept_proposal_still_approves_once_the_workbook_is_back_to_what_it_read(
    client: AsyncClient, catalog: Catalog, sessions: StubSessions, library: Path
) -> None:
    proposal = await a_researched_edit(catalog)
    sessions.pending = proposal
    os.utime(CATEGORY.copied_into(library), (EDITED_MTIME, EDITED_MTIME))
    stale = await client.post(f"/api/chat/proposals/{proposal.id}/approve")
    os.utime(CATEGORY.copied_into(library), (proposal.body.read_mtime, proposal.body.read_mtime))

    retried = await client.post(f"/api/chat/proposals/{proposal.id}/approve")

    assert stale.status_code == 409
    assert retried.status_code == 200
    assert retried.json()["rows"][0]["cells"][WATCH_KEY] == "Watched"
    assert sessions.written == [proposal.id]


async def test_the_same_researched_edit_lands_when_nothing_touched_the_workbook_meanwhile(
    client: AsyncClient, catalog: Catalog, sessions: StubSessions
) -> None:
    proposal = await a_researched_edit(catalog)
    sessions.pending = proposal

    response = await client.post(f"/api/chat/proposals/{proposal.id}/approve")

    assert response.status_code == 200
    assert response.json()["rows"][0]["cells"][WATCH_KEY] == "Watched"
    assert sessions.written == [proposal.id]


@pytest.mark.parametrize(
    ("cells", "expected_error", "named"),
    [
        ({"nonesuch": "anything"}, "UnknownColumnError", "nonesuch"),
        ({WATCH_KEY: "Definitely"}, "InvalidChoiceError", "Definitely"),
    ],
)
async def test_a_proposal_naming_a_cell_the_sheet_rejects_is_a_409_that_keeps_it(
    client: AsyncClient, sessions: StubSessions, library: Path, cells: dict[str, str], expected_error: str, named: str
) -> None:
    sessions.pending = Proposal(
        id=PROPOSAL_ID,
        summary="a change this sheet will not take",
        body={
            "kind": "edit",
            "category_id": CATEGORY.category_id,
            "read_mtime": category_mtime(library),
            "changes": [{"kind": "revise", "row": 2, "cells": cells}],
        },
    )

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/approve")

    assert response.status_code == 409
    assert response.json()["error"] == expected_error
    assert named in response.json()["message"]
    assert sessions.written == []


async def test_approving_a_create_builds_the_workbook_with_its_researched_cells(
    client: AsyncClient, sessions: StubSessions, library: Path
) -> None:
    sessions.pending = Proposal(
        id=PROPOSAL_ID,
        summary="a chronological wartime list",
        body={
            "kind": "create",
            "category": {
                "name": BUILT_CATEGORY_NAME,
                "columns": ["Order", "Title", "Notes"],
                "rows": [{"title": BUILT_TITLE, "notes": "Sept 1939 - Invasion of Poland"}],
            },
        },
    )

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/approve")

    assert response.status_code == 200
    built = response.json()
    assert built["name"] == BUILT_CATEGORY_STEM
    assert built["rows"][0]["cells"]["title"] == BUILT_TITLE
    assert (library / built["file_name"]).exists()
    assert sessions.written == [PROPOSAL_ID]


async def test_a_message_past_the_length_cap_never_reaches_the_model(
    client: AsyncClient, sessions: StubSessions
) -> None:
    response = await client.post(
        f"/api/chat/sessions/{SESSION_ID}/messages",
        json={"text": "x" * (MAX_CHAT_MESSAGE_LENGTH + 1)},
    )

    assert response.status_code == 422
    assert sessions.session.prompts == []


async def test_shutting_the_backend_down_ends_the_agent_runtime_with_it(
    sessions: StubSessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = StubRuntime(sessions)
    monkeypatch.setattr("tv_watchlist.main.get_agent_runtime", lambda: runtime)

    await run_lifespan(create_app())

    assert runtime.closed is True


async def test_the_cors_scope_the_app_already_had_covers_the_chat_routes(client: AsyncClient) -> None:
    origin = f"http://localhost:{get_settings().frontend_port}"

    response = await client.options(
        f"/api/chat/sessions/{SESSION_ID}/messages",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


async def test_a_second_edit_to_a_written_category_is_refused_at_propose_time_not_at_approve_time(
    catalog: Catalog,
) -> None:
    research = await a_researcher(catalog)

    async with client_for(catalog, research.sessions) as client:
        await research.read({"category_id": CATEGORY.category_id})
        approved = await an_approved_edit(client, research, FIRST_DATA_ROW)
        second = await research.propose({"summary": EDIT_SUMMARY, "body": an_edit_body(SHIFTED_ROW)})

    assert approved.status_code == 200
    assert second["is_error"] is True
    assert QUALIFIED_GET_CATEGORY_TOOL in second["content"][0]["text"]


async def test_reading_the_category_again_after_the_write_makes_the_next_edit_proposable_once_more(
    catalog: Catalog,
) -> None:
    research = await a_researcher(catalog)

    async with client_for(catalog, research.sessions) as client:
        await research.read({"category_id": CATEGORY.category_id})
        first = await an_approved_edit(client, research, FIRST_DATA_ROW)
        assert first.status_code == 200
        await research.read({"category_id": CATEGORY.category_id})
        second = await an_approved_edit(client, research, SHIFTED_ROW)

    assert second.status_code == 200


async def test_choosing_a_candidate_writes_that_image_and_returns_the_refreshed_category(
    client: AsyncClient, sessions: StubSessions, settings: Settings
) -> None:
    sessions.pending = Proposal(id=PROPOSAL_ID, summary=HERO_SUMMARY, body=HERO_BODY)

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/1")

    assert response.status_code == 200
    assert response.json()["hero_url"].split("?")[0] == f"/heroes/{CATEGORY.category_id}.png"
    assert (settings.heroes_dir / f"{CATEGORY.category_id}.png").read_bytes() == PNG
    assert sessions.written == [PROPOSAL_ID]


async def test_the_chosen_candidate_is_the_one_credited(
    client: AsyncClient, sessions: StubSessions, settings: Settings
) -> None:
    sessions.pending = Proposal(id=PROPOSAL_ID, summary=HERO_SUMMARY, body=HERO_BODY)

    await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/1")

    credited = (settings.heroes_dir / HERO_ATTRIBUTION_FILENAME).read_text(encoding="utf-8")
    assert SECOND_CANDIDATE_FILE in credited
    assert FIRST_CANDIDATE_FILE not in credited


async def test_approving_a_hero_proposal_is_refused_because_artwork_is_chosen_not_approved(
    client: AsyncClient, sessions: StubSessions, settings: Settings
) -> None:
    sessions.pending = Proposal(id=PROPOSAL_ID, summary=HERO_SUMMARY, body=HERO_BODY)

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/approve")

    assert response.status_code == 400
    assert response.json()["error"] == "HeroChoiceRequiredError"
    assert "candidate" in response.json()["message"]
    assert sessions.written == []
    assert list(settings.heroes_dir.glob("*")) == []


@pytest.mark.parametrize("choice", [2, 9])
async def test_choosing_a_candidate_that_is_not_on_offer_is_refused(
    client: AsyncClient, sessions: StubSessions, settings: Settings, choice: int
) -> None:
    sessions.pending = Proposal(id=PROPOSAL_ID, summary=HERO_SUMMARY, body=HERO_BODY)

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/{choice}")

    assert response.status_code == 400
    assert response.json()["error"] == "UnknownHeroCandidateError"
    assert sessions.written == []
    assert list(settings.heroes_dir.glob("*")) == []


async def test_choosing_a_negative_candidate_never_reaches_the_store(
    client: AsyncClient, sessions: StubSessions
) -> None:
    sessions.pending = Proposal(id=PROPOSAL_ID, summary=HERO_SUMMARY, body=HERO_BODY)

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/-1")

    assert response.status_code == 422
    assert sessions.written == []


async def test_choosing_a_candidate_of_a_proposal_that_offers_none_is_refused(
    client: AsyncClient, sessions: StubSessions, library: Path
) -> None:
    sessions.pending = an_edit_proposal(category_mtime(library))

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/0")

    assert response.status_code == 400
    assert response.json()["error"] == "NoHeroCandidatesError"
    assert sessions.written == []


async def test_choosing_artwork_for_a_category_that_is_gone_is_a_404_that_keeps_the_proposal(
    client: AsyncClient, sessions: StubSessions
) -> None:
    sessions.pending = Proposal(
        id=PROPOSAL_ID, summary=HERO_SUMMARY, body={**HERO_BODY, "category_id": "no-such-category"}
    )

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/0")

    assert response.status_code == 404
    assert response.json()["error"] == "CategoryNotFoundError"
    assert sessions.written == []


async def test_a_candidate_url_the_downloader_cannot_use_is_a_refusal_the_dock_can_show(
    client: AsyncClient, sessions: StubSessions, settings: Settings
) -> None:
    unusable = {**HERO_CANDIDATES[0], "url": "https://[::1"}
    sessions.pending = Proposal(id=PROPOSAL_ID, summary=HERO_SUMMARY, body={**HERO_BODY, "candidates": [unusable]})

    response = await client.post(f"/api/chat/proposals/{PROPOSAL_ID}/hero/0")

    assert response.status_code == 400
    assert response.json()["error"] == "BlockedUrlError"
    assert sessions.written == []
    assert list(settings.heroes_dir.glob("*")) == []
