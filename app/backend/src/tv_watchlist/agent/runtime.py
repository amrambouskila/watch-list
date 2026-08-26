"""What the whole agent feature owns while the backend is up."""

from __future__ import annotations

from claude_agent_sdk import ClaudeSDKClient

from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.registry import SessionRegistry
from tv_watchlist.agent.session import ChatSession, ClientFactory
from tv_watchlist.services.catalog import Catalog


class AgentRuntime:
    """One fetcher, one browser and one session registry, shut down together with the app."""

    def __init__(self, catalog: Catalog, fetcher: Fetcher, client_factory: ClientFactory = ClaudeSDKClient) -> None:
        self.catalog = catalog
        self.sessions = SessionRegistry(self._build_session)
        self._fetcher = fetcher
        self._client_factory = client_factory

    async def aclose(self) -> None:
        """End every conversation, then the browser they escalated to."""
        await self.sessions.aclose()
        await self._fetcher.aclose()

    def _build_session(self, session_id: str) -> ChatSession:
        return ChatSession(session_id, self.catalog, self._fetcher, client_factory=self._client_factory)
