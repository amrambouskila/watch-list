"""Every fixed value the research agent runs on."""

from __future__ import annotations

from typing import Final, Literal

from claude_agent_sdk import EffortLevel, PermissionMode

from tv_watchlist.constants import IN_PROGRESS, SKIPPED, UNWATCHED, WATCHED

AGENT_MODEL: Final[str] = "claude-opus-5"
AGENT_EFFORT: Final[EffortLevel] = "high"
AGENT_PERMISSION_MODE: Final[PermissionMode] = "dontAsk"
MAX_AGENT_TURNS: Final[int] = 40

BUILTIN_SEARCH_TOOL: Final[str] = "WebSearch"
LIBRARY_SERVER_NAME: Final[str] = "library"
LIBRARY_SERVER_VERSION: Final[str] = "1.0.0"
GET_CATEGORY_TOOL: Final[str] = "get_category"
FETCH_URL_TOOL: Final[str] = "fetch_url"
PROPOSE_TOOL: Final[str] = "propose"
MCP_TOOL_PREFIX: Final[str] = f"mcp__{LIBRARY_SERVER_NAME}__"
QUALIFIED_GET_CATEGORY_TOOL: Final[str] = f"{MCP_TOOL_PREFIX}{GET_CATEGORY_TOOL}"
QUALIFIED_FETCH_URL_TOOL: Final[str] = f"{MCP_TOOL_PREFIX}{FETCH_URL_TOOL}"
QUALIFIED_PROPOSE_TOOL: Final[str] = f"{MCP_TOOL_PREFIX}{PROPOSE_TOOL}"
AGENT_ALLOWED_TOOLS: Final[tuple[str, ...]] = (
    BUILTIN_SEARCH_TOOL,
    QUALIFIED_FETCH_URL_TOOL,
    QUALIFIED_GET_CATEGORY_TOOL,
    QUALIFIED_PROPOSE_TOOL,
)

HTTP_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
DEFAULT_PORT_BY_SCHEME: Final[dict[str, int]] = {"http": 80, "https": 443}
FETCH_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT_SECONDS: Final[float] = 20.0
MAX_FETCH_BYTES: Final[int] = 4_000_000
MAX_FETCH_CHARS: Final[int] = 30_000
MAX_FETCH_REDIRECTS: Final[int] = 5
REDIRECT_STATUS_CODES: Final[frozenset[int]] = frozenset({301, 302, 303, 307, 308})
BLOCK_STATUS_CODES: Final[frozenset[int]] = frozenset({401, 403, 405, 406, 429, 451})
CHALLENGE_MARKERS: Final[tuple[str, ...]] = (
    "just a moment",
    "enable javascript and cookies",
    "cf-browser-verification",
    "checking your browser",
    "captcha",
    "are you a robot",
)
MIN_RENDERED_CHARS: Final[int] = 200
MAX_TOOL_RESULT_CHARS: Final[int] = 48_000

BROWSER_TIMEOUT_MS: Final[int] = 45_000
BROWSER_BODY_TEXT_SCRIPT: Final[str] = "document.body ? document.body.innerText : ''"
PAGE_LOAD_STATE: Final[Literal["domcontentloaded"]] = "domcontentloaded"
SETTLED_LOAD_STATE: Final[Literal["load"]] = "load"
SETTLE_TIMEOUT_MS: Final[int] = 5_000

UNTRUSTED_CONTENT_OPEN: Final[str] = "<<<UNTRUSTED_WEB_CONTENT>>>"
UNTRUSTED_CONTENT_CLOSE: Final[str] = "<<<END_UNTRUSTED_WEB_CONTENT>>>"

TOOL_STATE_RUNNING: Final[str] = "running"
TOOL_STATE_DONE: Final[str] = "done"
TOOL_STATE_ESCALATED: Final[str] = "escalated"
TOOL_STATE_FAILED: Final[str] = "failed"
MAX_TOOL_DETAIL_CHARS: Final[int] = 120
RATE_LIMIT_ERROR_CODE: Final[str] = "RateLimit"
CONVERSATION_RESET_ERROR_CODE: Final[str] = "ConversationReset"
USER_REQUEST_HEADER: Final[str] = "USER REQUEST"

SESSION_IDLE_SECONDS: Final[float] = 3600.0

DIGEST_TITLE_SEPARATOR: Final[str] = " | "
DIGEST_COLUMN_SEPARATOR: Final[str] = ", "
DIGEST_UNKNOWN_STATUS_MARKER: Final[str] = "?"
DIGEST_STATUS_MARKERS: Final[dict[str, str]] = {
    WATCHED: "x",
    IN_PROGRESS: "~",
    SKIPPED: "-",
    UNWATCHED: " ",
}
