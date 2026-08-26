"""Session id to live session, with idle eviction; conversations die with the backend."""

from __future__ import annotations

import time
from collections.abc import Callable
from uuid import uuid4

from tv_watchlist.agent.constants import SESSION_IDLE_SECONDS
from tv_watchlist.agent.errors import UnknownProposalError, UnknownSessionError
from tv_watchlist.agent.session import ChatSession
from tv_watchlist.models.proposal import Proposal

SessionFactory = Callable[[str], ChatSession]
Clock = Callable[[], float]


class SessionRegistry:
    """Every live chat session, and the proposals they are holding."""

    def __init__(
        self,
        create_session: SessionFactory,
        idle_seconds: float = SESSION_IDLE_SECONDS,
        clock: Clock = time.monotonic,
    ) -> None:
        self._create_session = create_session
        self._idle_seconds = idle_seconds
        self._clock = clock
        self._sessions: dict[str, ChatSession] = {}
        self._touched: dict[str, float] = {}

    async def create(self) -> ChatSession:
        """A new started session, ready to take a message."""
        await self._evict_idle()
        session = self._create_session(uuid4().hex)
        await session.start()
        self._sessions[session.id] = session
        self._touched[session.id] = self._clock()
        return session

    async def get(self, session_id: str) -> ChatSession:
        """The live session with this id, refreshing its idle clock."""
        await self._evict_idle()
        session = self._sessions.get(session_id)
        if session is None:
            raise UnknownSessionError(session_id)
        self._touched[session_id] = self._clock()
        return session

    async def close(self, session_id: str) -> None:
        """End one session and forget it."""
        session = self._sessions.get(session_id)
        if session is None:
            raise UnknownSessionError(session_id)
        await self._forget(session_id)

    async def aclose(self) -> None:
        """End every session, for backend shutdown."""
        for session_id in list(self._sessions):
            await self._forget(session_id)

    def proposal(self, proposal_id: str) -> Proposal:
        """The pending proposal with this id, whichever session is holding it."""
        found = self._holder(proposal_id)
        if found is None:
            raise UnknownProposalError(proposal_id)
        return found[1]

    def applied(self, proposal_id: str) -> None:
        """Let go of a proposal that reached its workbook, along with the read stamp that write spent."""
        found = self._holder(proposal_id)
        if found is None:
            raise UnknownProposalError(proposal_id)
        found[0].mark_applied(found[1])

    def _holder(self, proposal_id: str) -> tuple[ChatSession, Proposal] | None:
        for session in self._sessions.values():
            pending = session.pending_proposal
            if pending is not None and pending.id == proposal_id:
                return session, pending
        return None

    async def _forget(self, session_id: str) -> None:
        session = self._sessions.pop(session_id)
        self._touched.pop(session_id, None)
        await session.aclose()

    async def _evict_idle(self) -> None:
        deadline = self._clock() - self._idle_seconds
        for session_id in [key for key, touched in self._touched.items() if touched < deadline]:
            await self._forget(session_id)
