"""One session, one client, and a dispatch that covers all seven Message union members."""

from __future__ import annotations

import json

import httpx
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ConversationResetMessage,
    McpSdkServerConfig,
    Message,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from mock_responder import MockResponder
from recording_reader import RecordingReader
from stub_client import StubClient

from tv_watchlist.agent import session as session_module
from tv_watchlist.agent.constants import (
    QUALIFIED_FETCH_URL_TOOL,
    QUALIFIED_PROPOSE_TOOL,
    TOOL_STATE_DONE,
    TOOL_STATE_ESCALATED,
    TOOL_STATE_FAILED,
    TOOL_STATE_RUNNING,
)
from tv_watchlist.agent.fetch_result import BROWSER_TRANSPORT, CHEAP_TRANSPORT
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.server import build_library_server
from tv_watchlist.agent.session import ChatSession
from tv_watchlist.agent.tools.propose import ProposalRecorder
from tv_watchlist.models.chat_event import ChatEvent
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.services.catalog import Catalog

SESSION_ID = "session-1"
REQUEST = "build me a wartime list"
READ_MTIME = 1_700_000_000.5
EDIT_CATEGORY = "a-category"
PROPOSAL = Proposal(
    id="p1",
    summary="91 wartime films",
    sources=["https://example.com"],
    body={
        "kind": "edit",
        "category_id": EDIT_CATEGORY,
        "read_mtime": READ_MTIME,
        "changes": [],
    },
)
CREATE_PROPOSAL = Proposal(
    id="p2",
    summary="a chronological wartime list",
    body={
        "kind": "create",
        "category": {"name": "Wartime Films", "columns": ["Order", "Title"], "rows": [{"title": "Dunkirk"}]},
    },
)


def a_result(
    *,
    is_error: bool = False,
    subtype: str = "success",
    num_turns: int = 7,
    total_cost_usd: float = 0.14,
    result: str | None = None,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=8,
        is_error=is_error,
        num_turns=num_turns,
        session_id=SESSION_ID,
        total_cost_usd=total_cost_usd,
        result=result,
    )


def a_fetcher() -> Fetcher:
    return Fetcher(RecordingReader(), transport=MockResponder(httpx.Response(200)).transport)


@pytest.fixture
def session(catalog: Catalog) -> ChatSession:
    return ChatSession(SESSION_ID, catalog, a_fetcher(), client_factory=StubClient)


def stub_of(session: ChatSession) -> StubClient:
    client = session.client
    assert isinstance(client, StubClient)
    return client


async def replay(session: ChatSession, *messages: Message) -> list[ChatEvent]:
    stub_of(session).messages = list(messages)
    return [event async for event in session.send(REQUEST)]


async def test_starting_a_session_connects_its_client(session: ChatSession) -> None:
    await session.start()

    assert stub_of(session).connected is True


async def test_the_client_is_built_with_the_agent_options(session: ChatSession) -> None:
    assert isinstance(stub_of(session).options, ClaudeAgentOptions)
    assert stub_of(session).options.setting_sources == []


async def test_the_first_prompt_carries_the_library_digest_and_later_ones_do_not(session: ChatSession) -> None:
    await replay(session, a_result())
    await replay(session, a_result())

    prompts = stub_of(session).prompts
    assert "LIBRARY DIGEST" in prompts[0]
    assert REQUEST in prompts[0]
    assert prompts[1] == REQUEST


async def test_assistant_text_becomes_a_text_frame(session: ChatSession) -> None:
    message = AssistantMessage(content=[TextBlock(text="Searching for lists")], model="m")

    events = await replay(session, message, a_result())

    assert events[0].type == "text"
    assert events[0].text == "Searching for lists"


async def test_thinking_blocks_are_not_streamed_to_the_dock(session: ChatSession) -> None:
    message = AssistantMessage(content=[ThinkingBlock(thinking="hmm", signature="s")], model="m")

    events = await replay(session, message, a_result())

    assert [event.type for event in events] == ["done"]


async def test_a_tool_call_becomes_a_running_chip_naming_what_it_was_given(session: ChatSession) -> None:
    use = ToolUseBlock(id="t1", name=QUALIFIED_FETCH_URL_TOOL, input={"url": "https://reddit.com/r/movies"})

    events = await replay(session, AssistantMessage(content=[use], model="m"), a_result())

    assert events[0].type == "tool"
    assert events[0].name == QUALIFIED_FETCH_URL_TOOL
    assert events[0].detail == "https://reddit.com/r/movies"
    assert events[0].state == TOOL_STATE_RUNNING


async def test_a_tool_result_closes_the_chip_it_opened(session: ChatSession) -> None:
    use = ToolUseBlock(id="t1", name=QUALIFIED_FETCH_URL_TOOL, input={"url": "https://reddit.com/r/movies"})
    done = UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok")])

    events = await replay(session, AssistantMessage(content=[use], model="m"), done, a_result())

    assert events[1].state == TOOL_STATE_DONE
    assert events[1].name == QUALIFIED_FETCH_URL_TOOL
    assert events[1].detail == "https://reddit.com/r/movies"


async def test_a_failed_tool_result_marks_the_chip_failed(session: ChatSession) -> None:
    use = ToolUseBlock(id="t1", name=QUALIFIED_FETCH_URL_TOOL, input={"url": "https://reddit.com/r/movies"})
    failed = UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="blocked", is_error=True)])

    events = await replay(session, AssistantMessage(content=[use], model="m"), failed, a_result())

    assert events[1].state == TOOL_STATE_FAILED


async def test_a_plain_text_user_message_produces_nothing(session: ChatSession) -> None:
    events = await replay(session, UserMessage(content="anything"), a_result())

    assert [event.type for event in events] == ["done"]


async def test_a_recorded_proposal_is_emitted_when_the_propose_tool_returns(session: ChatSession) -> None:
    use = ToolUseBlock(id="t9", name=QUALIFIED_PROPOSE_TOOL, input={"summary": "91 wartime films"})
    await session.record_proposal(PROPOSAL)
    done = UserMessage(content=[ToolResultBlock(tool_use_id="t9", content="{}")])

    events = await replay(session, AssistantMessage(content=[use], model="m"), done, a_result())

    assert [event.type for event in events] == ["tool", "tool", "proposal", "done"]
    assert events[2].proposal == PROPOSAL
    assert session.pending_proposal == PROPOSAL


async def test_system_messages_are_ignored_rather_than_streamed(session: ChatSession) -> None:
    events = await replay(session, SystemMessage(subtype="init", data={}), a_result())

    assert [event.type for event in events] == ["done"]


async def test_partial_stream_events_are_ignored_rather_than_streamed(session: ChatSession) -> None:
    partial = StreamEvent(uuid="u1", session_id=SESSION_ID, event={"type": "content_block_delta"})

    events = await replay(session, partial, a_result())

    assert [event.type for event in events] == ["done"]


async def test_a_rate_limit_event_surfaces_as_an_error_frame(session: ChatSession) -> None:
    limit = RateLimitEvent(rate_limit_info=RateLimitInfo(status="rejected"), uuid="u2", session_id=SESSION_ID)

    events = await replay(session, limit, a_result())

    assert events[0].type == "error"
    assert "rejected" in (events[0].message or "")


async def test_a_conversation_reset_surfaces_as_an_error_frame(session: ChatSession) -> None:
    reset = ConversationResetMessage(new_conversation_id="c2", uuid="u3", session_id=SESSION_ID)

    events = await replay(session, reset, a_result())

    assert events[0].type == "error"


async def test_the_done_frame_reads_total_cost_usd_not_cost_usd(session: ChatSession) -> None:
    events = await replay(session, a_result(num_turns=7, total_cost_usd=0.14))

    assert events[-1].type == "done"
    assert events[-1].turns == 7
    assert events[-1].total_cost_usd == 0.14


async def test_a_failed_result_reports_the_error_before_it_reports_done(session: ChatSession) -> None:
    failure = a_result(is_error=True, subtype="error_max_turns", result="ran out of turns")

    events = await replay(session, failure)

    assert [event.type for event in events] == ["error", "done"]
    assert events[0].code == "error_max_turns"


async def test_closing_a_session_disconnects_its_client(session: ChatSession) -> None:
    await session.start()

    await session.aclose()

    assert stub_of(session).connected is False


async def test_abandoning_a_session_retires_its_client_and_stands_a_fresh_one_behind_it(
    session: ChatSession,
) -> None:
    await session.start()
    retired = stub_of(session)

    await session.abandon()

    assert retired.connected is False
    assert stub_of(session) is not retired


async def test_the_turn_after_an_abandon_connects_the_fresh_client_and_digests_the_library_again(
    session: ChatSession,
) -> None:
    await replay(session, a_result())
    await session.abandon()

    events = await replay(session, a_result())

    fresh = stub_of(session)
    assert fresh.connected is True
    assert "LIBRARY DIGEST" in fresh.prompts[0]
    assert [event.type for event in events] == ["done"]


async def fetch_state(session: ChatSession, content: str | list[dict[str, object]]) -> str | None:
    """The chip state a finished fetch_url call reports, given the payload the tool handed back."""
    use = ToolUseBlock(id="t1", name=QUALIFIED_FETCH_URL_TOOL, input={"url": "https://reddit.com/r/movies"})
    done = UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=content)])
    events = await replay(session, AssistantMessage(content=[use], model="m"), done, a_result())
    return events[1].state


async def test_a_fetch_the_browser_had_to_render_marks_the_chip_escalated(session: ChatSession) -> None:
    payload = json.dumps({"text": "page", "via": BROWSER_TRANSPORT, "truncated": False})

    assert await fetch_state(session, [{"type": "text", "text": payload}]) == TOOL_STATE_ESCALATED


async def test_a_fetch_the_cheap_path_read_leaves_the_chip_merely_done(session: ChatSession) -> None:
    payload = json.dumps({"text": "page", "via": CHEAP_TRANSPORT, "truncated": False})

    assert await fetch_state(session, [{"type": "text", "text": payload}]) == TOOL_STATE_DONE


async def test_a_fetch_result_that_is_not_the_expected_payload_still_closes_the_chip(session: ChatSession) -> None:
    assert await fetch_state(session, "not json at all") == TOOL_STATE_DONE


def captured_read_logs(monkeypatch: pytest.MonkeyPatch) -> list[ReadLog]:
    """The read log handed to the library tools, collected as sessions are built."""
    logs: list[ReadLog] = []

    def capture(catalog: Catalog, fetcher: Fetcher, record: ProposalRecorder, read_log: ReadLog) -> McpSdkServerConfig:
        logs.append(read_log)
        return build_library_server(catalog, fetcher, record, read_log)

    monkeypatch.setattr(session_module, "build_library_server", capture)
    return logs


async def test_each_session_gives_its_library_tools_a_read_log_of_its_own(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = captured_read_logs(monkeypatch)

    ChatSession(SESSION_ID, catalog, a_fetcher(), client_factory=StubClient)
    ChatSession("session-2", catalog, a_fetcher(), client_factory=StubClient)

    assert [isinstance(log, ReadLog) for log in logs] == [True, True]
    assert logs[0] is not logs[1]


async def test_the_read_log_a_session_hands_its_tools_is_the_one_it_keeps(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = captured_read_logs(monkeypatch)

    session = ChatSession(SESSION_ID, catalog, a_fetcher(), client_factory=StubClient)

    assert session.read_log is logs[0]


async def test_an_applied_edit_clears_the_proposal_and_forgets_the_stamp_its_write_spent(
    session: ChatSession,
) -> None:
    session.read_log.record(EDIT_CATEGORY, READ_MTIME)
    await session.record_proposal(PROPOSAL)

    session.mark_applied(PROPOSAL)

    assert session.pending_proposal is None
    assert session.read_log.mtime_of(EDIT_CATEGORY) is None


async def test_an_applied_create_clears_the_proposal_and_leaves_every_stamp_standing(
    session: ChatSession,
) -> None:
    session.read_log.record(EDIT_CATEGORY, READ_MTIME)
    await session.record_proposal(CREATE_PROPOSAL)

    session.mark_applied(CREATE_PROPOSAL)

    assert session.pending_proposal is None
    assert session.read_log.mtime_of(EDIT_CATEGORY) == READ_MTIME
