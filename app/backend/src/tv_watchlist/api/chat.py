"""Chat endpoints: one session per dock, one SSE stream per turn, and the approve write."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Final

import anyio
from fastapi import APIRouter, Body, Depends, Path, status
from fastapi.responses import JSONResponse, StreamingResponse

from tv_watchlist.agent.dependencies import get_agent_runtime
from tv_watchlist.agent.errors import HeroChoiceRequiredError, NoHeroCandidatesError, UnknownHeroCandidateError
from tv_watchlist.agent.runtime import AgentRuntime
from tv_watchlist.agent.session import ChatSession
from tv_watchlist.api.dependencies import get_catalog, get_hero_store
from tv_watchlist.api.errors import payload_for
from tv_watchlist.constants import MAX_CHAT_MESSAGE_LENGTH
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.proposal_create import ProposalCreate
from tv_watchlist.models.proposal_edit import ProposalEdit
from tv_watchlist.models.proposal_hero import ProposalHero
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.hero_store import HeroStore
from tv_watchlist.workbook.errors import (
    InvalidChoiceError,
    StaleWorkbookError,
    UnknownColumnError,
    WorkbookError,
    WorkbookLockedError,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])

FIRST_CANDIDATE: Final[int] = 0

RuntimeDep = Annotated[AgentRuntime, Depends(get_agent_runtime)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
HeroStoreDep = Annotated[HeroStore, Depends(get_hero_store)]
ChoiceParam = Annotated[int, Path(ge=FIRST_CANDIDATE)]

_SSE_MEDIA_TYPE: Final[str] = "text/event-stream"
_SSE_DATA_PREFIX: Final[str] = "data: "
_SSE_FRAME_END: Final[str] = "\n\n"
# Inert against the Vite dev proxy, and the whole defence against a buffering production one.
_STREAM_HEADERS: Final[dict[str, str]] = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}

# A proposal that cannot be written right now is a conflict you retry, not a bad request: the diff is
# still on screen and the proposal stays pending on its session.
_APPROVE_CONFLICTS: Final[tuple[type[WorkbookError], ...]] = (
    WorkbookLockedError,
    StaleWorkbookError,
    UnknownColumnError,
    InvalidChoiceError,
)


async def sse_frames(session: ChatSession, text: str) -> AsyncIterator[str]:
    """One turn as SSE lines; a dock that goes away mid-turn retires the conversation it half-read."""
    try:
        async for event in session.send(text):
            yield f"{_SSE_DATA_PREFIX}{event.model_dump_json(exclude_none=True)}{_SSE_FRAME_END}"
    except (asyncio.CancelledError, GeneratorExit):
        # Starlette abandons this generator in two shapes, and only one of them is a cancellation:
        # a cancel reaches the generator when the response task was suspended inside it, and a plain
        # close reaches it when the task was suspended in its own `send` instead. Both leave a turn
        # half-read, so both have to retire it. Shielded because a cancelled scope goes on
        # re-delivering, so an unshielded await here aborts at its first suspension — which is how
        # the interrupt this replaced was lost.
        with anyio.CancelScope(shield=True):
            await session.abandon()
        raise


async def _applied(catalog: Catalog, body: ProposalCreate | ProposalEdit) -> CategoryDetail:
    """Run a proposal body through the same catalog calls the REST endpoints use."""
    if isinstance(body, ProposalCreate):
        return await catalog.create_category(body.category)
    return await catalog.apply_changes(body.category_id, body.changes, body.read_mtime)


@router.post("/sessions")
async def open_session(runtime: RuntimeDep) -> dict[str, str]:
    """Start a conversation and hand back the id every later call addresses it by."""
    session = await runtime.sessions.create()
    return {"session_id": session.id}


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    runtime: RuntimeDep,
    text: Annotated[str, Body(embed=True, max_length=MAX_CHAT_MESSAGE_LENGTH)],
) -> StreamingResponse:
    """Ask Claude one thing, streaming a frame per event until the turn ends."""
    session = await runtime.sessions.get(session_id)
    return StreamingResponse(sse_frames(session, text), media_type=_SSE_MEDIA_TYPE, headers=_STREAM_HEADERS)


@router.post("/proposals/{proposal_id}/approve", response_model=CategoryDetail)
async def approve_proposal(proposal_id: str, runtime: RuntimeDep, catalog: CatalogDep) -> CategoryDetail | JSONResponse:
    """Write what Claude proposed, guarded against the workbook its row numbers were resolved on."""
    proposal = runtime.sessions.proposal(proposal_id)
    if isinstance(proposal.body, ProposalHero):
        raise HeroChoiceRequiredError(proposal_id)
    try:
        detail = await _applied(catalog, proposal.body)
    except _APPROVE_CONFLICTS as error:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=payload_for(error))
    runtime.sessions.applied(proposal_id)
    return detail


@router.post("/proposals/{proposal_id}/hero/{choice}", response_model=CategoryDetail)
async def choose_hero(
    proposal_id: str, choice: ChoiceParam, runtime: RuntimeDep, store: HeroStoreDep
) -> CategoryDetail:
    """Download the candidate the user picked by eye and make it that category's card artwork."""
    proposal = runtime.sessions.proposal(proposal_id)
    body = proposal.body
    if not isinstance(body, ProposalHero):
        raise NoHeroCandidatesError(proposal_id)
    if choice >= len(body.candidates):
        raise UnknownHeroCandidateError(str(choice))
    detail = await store.save(body.category_id, body.candidates[choice])
    runtime.sessions.applied(proposal_id)
    return detail


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_session(session_id: str, runtime: RuntimeDep) -> None:
    """End a conversation, dropping whatever proposal it was still holding."""
    await runtime.sessions.close(session_id)
