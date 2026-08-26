"""The process-wide agent runtime, built on the catalog the REST endpoints already share."""

from __future__ import annotations

from functools import lru_cache

from tv_watchlist.agent.browser import ChromiumReader
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.runtime import AgentRuntime
from tv_watchlist.api.dependencies import get_catalog


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime:
    """One runtime for the whole process; the browser inside it starts on first escalation."""
    return AgentRuntime(get_catalog(), Fetcher(ChromiumReader()))
