"""The options one chat session runs Claude under."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, McpSdkServerConfig

from tv_watchlist.agent.constants import (
    AGENT_ALLOWED_TOOLS,
    AGENT_EFFORT,
    AGENT_MODEL,
    AGENT_PERMISSION_MODE,
    BUILTIN_SEARCH_TOOL,
    LIBRARY_SERVER_NAME,
    MAX_AGENT_TURNS,
)
from tv_watchlist.agent.prompt import RESEARCH_SYSTEM_PROMPT


def build_agent_options(server: McpSdkServerConfig, library_dir: Path) -> ClaudeAgentOptions:
    """Everything explicit: an omitted setting here inherits the machine's own Claude config."""
    return ClaudeAgentOptions(
        model=AGENT_MODEL,
        effort=AGENT_EFFORT,
        system_prompt=RESEARCH_SYSTEM_PROMPT,
        setting_sources=[],
        tools=[BUILTIN_SEARCH_TOOL],
        mcp_servers={LIBRARY_SERVER_NAME: server},
        allowed_tools=list(AGENT_ALLOWED_TOOLS),
        permission_mode=AGENT_PERMISSION_MODE,
        cwd=library_dir,
        max_turns=MAX_AGENT_TURNS,
        env={},
    )
