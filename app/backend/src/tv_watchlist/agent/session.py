"""One browser session's conversation: one SDK client, one pending proposal, one event stream."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ConversationResetMessage,
    Message,
    RateLimitEvent,
    ResultMessage,
    ServerToolUseBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from pydantic import ValidationError

from tv_watchlist.agent.agent_client import AgentClient
from tv_watchlist.agent.constants import (
    CONVERSATION_RESET_ERROR_CODE,
    MAX_TOOL_DETAIL_CHARS,
    QUALIFIED_FETCH_URL_TOOL,
    QUALIFIED_PROPOSE_TOOL,
    RATE_LIMIT_ERROR_CODE,
    TOOL_STATE_DONE,
    TOOL_STATE_ESCALATED,
    TOOL_STATE_FAILED,
    TOOL_STATE_RUNNING,
    USER_REQUEST_HEADER,
)
from tv_watchlist.agent.digest import build_library_digest
from tv_watchlist.agent.fetch_result import BROWSER_TRANSPORT, FetchResult
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.options import build_agent_options
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.server import build_library_server
from tv_watchlist.models.chat_event import ChatEvent
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.models.proposal_edit import ProposalEdit
from tv_watchlist.services.catalog import Catalog

ClientFactory = Callable[[ClaudeAgentOptions], AgentClient]


def _detail_of(payload: dict[str, object]) -> str:
    """The first string argument, which is the URL, category id or summary worth showing on a chip."""
    value = next((item for item in payload.values() if isinstance(item, str)), "")
    return value[:MAX_TOOL_DETAIL_CHARS]


def _payload_of(content: str | list[dict[str, object]] | None) -> str:
    """A tool result reaches us either as one string or as the SDK's list of text blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(str(block.get("text", "")) for block in content)


def _state_of(name: str, block: ToolResultBlock) -> str:
    """A fetch the cheap path could not read says so in its payload, and the chip shows it."""
    if block.is_error:
        return TOOL_STATE_FAILED
    if name != QUALIFIED_FETCH_URL_TOOL:
        return TOOL_STATE_DONE
    try:
        read = FetchResult.model_validate_json(_payload_of(block.content))
    except ValidationError:
        return TOOL_STATE_DONE
    return TOOL_STATE_ESCALATED if read.via == BROWSER_TRANSPORT else TOOL_STATE_DONE


class ChatSession:
    """Holds one `ClaudeSDKClient`, turns its messages into chat frames, and keeps the pending proposal."""

    def __init__(
        self,
        session_id: str,
        catalog: Catalog,
        fetcher: Fetcher,
        client_factory: ClientFactory = ClaudeSDKClient,
    ) -> None:
        self.id = session_id
        self.pending_proposal: Proposal | None = None
        self.read_log = ReadLog()
        self._catalog = catalog
        self._calls: dict[str, tuple[str, str]] = {}
        self._digested = False
        self._client_factory = client_factory
        server = build_library_server(catalog, fetcher, self.record_proposal, self.read_log)
        self._options = build_agent_options(server, catalog.library_dir)
        self.client = client_factory(self._options)
        self._connected = False

    async def start(self) -> None:
        """Open the CLI connection this session talks over."""
        await self._connect()

    async def send(self, text: str) -> AsyncIterator[ChatEvent]:
        """Ask Claude, streaming one frame per thing worth showing."""
        if not self._connected:
            await self._connect()
        await self.client.query(await self._prompt_for(text))
        async for message in self.client.receive_response():
            for event in self._events_for(message):
                yield event

    async def abandon(self) -> None:
        """
        Retire the CLI conversation a stopped turn left half-read, standing a fresh one behind it.

        One client multiplexes every turn over a single buffered stream, so a turn nobody finished
        reading leaves its tail and its own result frame queued; the next turn would read those and
        end on them, and a turn longer than the buffer would wedge the CLI outright. There is no
        point to resynchronise on, so the conversation goes and the dock keeps its id, its
        transcript, its pending proposal and its read stamps.
        """
        await self.client.disconnect()
        self.client = self._client_factory(self._options)
        self._connected = False
        self._digested = False

    async def aclose(self) -> None:
        """End the conversation and the CLI subprocess behind it."""
        await self.client.disconnect()
        self._connected = False

    async def _connect(self) -> None:
        await self.client.connect()
        self._connected = True

    async def record_proposal(self, proposal: Proposal) -> None:
        """Hold what the propose tool validated, until the user approves or discards it."""
        self.pending_proposal = proposal

    def mark_applied(self, proposal: Proposal) -> None:
        """Let go of a proposal that reached a workbook, and of the read stamp its write just spent."""
        self.pending_proposal = None
        if isinstance(proposal.body, ProposalEdit):
            self.read_log.forget(proposal.body.category_id)

    async def _prompt_for(self, text: str) -> str:
        if self._digested:
            return text
        self._digested = True
        digest = await build_library_digest(self._catalog)
        return f"{digest}\n\n{USER_REQUEST_HEADER}\n{text}"

    def _events_for(self, message: Message) -> list[ChatEvent]:
        if isinstance(message, AssistantMessage):
            return self._assistant_events(message)
        if isinstance(message, UserMessage):
            return self._user_events(message)
        if isinstance(message, ResultMessage):
            return self._result_events(message)
        if isinstance(message, RateLimitEvent):
            info = message.rate_limit_info
            return [
                ChatEvent(
                    type="error",
                    code=RATE_LIMIT_ERROR_CODE,
                    message=f"Claude usage limit {info.status} ({info.rate_limit_type or 'unknown window'}).",
                )
            ]
        if isinstance(message, ConversationResetMessage):
            return [
                ChatEvent(
                    type="error",
                    code=CONVERSATION_RESET_ERROR_CODE,
                    message="This conversation was reset, so Claude no longer remembers the earlier turns.",
                )
            ]
        # SystemMessage and StreamEvent are CLI bookkeeping with nothing to show.
        return []

    def _assistant_events(self, message: AssistantMessage) -> list[ChatEvent]:
        events: list[ChatEvent] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                events.append(ChatEvent(type="text", text=block.text))
            elif isinstance(block, ToolUseBlock | ServerToolUseBlock):
                detail = _detail_of(block.input)
                self._calls[block.id] = (block.name, detail)
                events.append(ChatEvent(type="tool", name=block.name, detail=detail, state=TOOL_STATE_RUNNING))
        return events

    def _user_events(self, message: UserMessage) -> list[ChatEvent]:
        if isinstance(message.content, str):
            return []
        events: list[ChatEvent] = []
        for block in message.content:
            if not isinstance(block, ToolResultBlock):
                continue
            name, detail = self._calls.get(block.tool_use_id, ("", ""))
            state = _state_of(name, block)
            events.append(ChatEvent(type="tool", name=name, detail=detail, state=state))
            if name == QUALIFIED_PROPOSE_TOOL and state == TOOL_STATE_DONE and self.pending_proposal is not None:
                events.append(ChatEvent(type="proposal", proposal=self.pending_proposal))
        return events

    def _result_events(self, message: ResultMessage) -> list[ChatEvent]:
        events: list[ChatEvent] = []
        if message.is_error:
            events.append(ChatEvent(type="error", code=message.subtype, message=message.result or message.subtype))
        events.append(ChatEvent(type="done", turns=message.num_turns, total_cost_usd=message.total_cost_usd))
        return events
