"""Assemble the three library tools into the in-process MCP server the agent talks to."""

from __future__ import annotations

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server

from tv_watchlist.agent.constants import LIBRARY_SERVER_NAME, LIBRARY_SERVER_VERSION
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.tools.fetch_url import build_fetch_url_tool
from tv_watchlist.agent.tools.get_category import build_get_category_tool
from tv_watchlist.agent.tools.propose import ProposalRecorder, build_propose_tool
from tv_watchlist.services.catalog import Catalog


def build_library_server(
    catalog: Catalog, fetcher: Fetcher, record: ProposalRecorder, read_log: ReadLog
) -> McpSdkServerConfig:
    """The library server for one chat session, bound to that session's proposal recorder and read log."""
    return create_sdk_mcp_server(
        name=LIBRARY_SERVER_NAME,
        version=LIBRARY_SERVER_VERSION,
        tools=[
            build_get_category_tool(catalog, read_log),
            build_fetch_url_tool(fetcher),
            build_propose_tool(record, read_log),
        ],
    )
