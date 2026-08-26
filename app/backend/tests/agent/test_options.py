"""The agent options, where every wrong default costs money or leaks the user's global config."""

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
from tv_watchlist.agent.options import build_agent_options
from tv_watchlist.agent.prompt import RESEARCH_SYSTEM_PROMPT

SERVER: McpSdkServerConfig = {"type": "sdk", "name": LIBRARY_SERVER_NAME, "instance": object()}
LIBRARY = Path("C:/library")


def built() -> ClaudeAgentOptions:
    return build_agent_options(SERVER, LIBRARY)


def test_setting_sources_is_an_empty_list_because_none_means_inherit_the_users_whole_config() -> None:
    assert built().setting_sources == []


def test_the_system_prompt_is_explicit_because_none_emits_an_empty_prompt() -> None:
    assert built().system_prompt == RESEARCH_SYSTEM_PROMPT


def test_only_the_built_in_search_tool_is_available() -> None:
    assert built().tools == [BUILTIN_SEARCH_TOOL]


def test_the_permission_allowlist_names_the_search_tool_and_the_three_library_tools() -> None:
    assert built().allowed_tools == list(AGENT_ALLOWED_TOOLS)


def test_permissions_are_deny_by_default() -> None:
    assert built().permission_mode == AGENT_PERMISSION_MODE


def test_the_library_server_is_mounted_under_its_own_name() -> None:
    assert built().mcp_servers == {LIBRARY_SERVER_NAME: SERVER}


def test_the_model_effort_and_turn_ceiling_come_from_constants() -> None:
    options = built()

    assert (options.model, options.effort, options.max_turns) == (AGENT_MODEL, AGENT_EFFORT, MAX_AGENT_TURNS)


def test_the_subprocess_runs_in_the_library_folder_with_no_inherited_environment() -> None:
    options = built()

    assert options.cwd == LIBRARY
    assert options.env == {}
