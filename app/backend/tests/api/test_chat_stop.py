"""What pressing Stop has to guarantee: the CLI turn ends, and the next question gets its own answer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Final

import anyio
import httpx
import pytest
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock
from mock_responder import MockResponder
from recording_reader import RecordingReader
from scripted_cli import ScriptedCli
from stub_client import StubClient

from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.session import ChatSession
from tv_watchlist.api.chat import sse_frames
from tv_watchlist.services.catalog import Catalog

SESSION_ID: Final[str] = "session-1"
FIRST_REQUEST: Final[str] = "chart the wartime films"
SECOND_REQUEST: Final[str] = "no, chart the space films"
# Enough prose that a turn stopped after its first frame still has a tail left to leak into the next.
PROSE_FRAMES_PER_TURN: Final[int] = 3
DATA_PREFIX: Final[str] = "data: "
# Two lines, so the stream is still suspended between them when the stop lands.
SPOKEN_LINES: Final[tuple[str, str]] = ("researching", "still researching")
# Past the SDK's own 100-slot buffer, so the abandoned turn is one its reader is parked inside.
FRAMES_PAST_THE_BUFFER: Final[int] = 400
# Long enough that a real wedge fails the test rather than hanging the suite.
TURN_PATIENCE_SECONDS: Final[int] = 30


def a_fetcher() -> Fetcher:
    return Fetcher(RecordingReader(), transport=MockResponder(httpx.Response(200)).transport)


def a_session(
    catalog: Catalog, cli_log: list[ScriptedCli], frames_per_turn: int = PROSE_FRAMES_PER_TURN
) -> ChatSession:
    """A real session whose every CLI is a scripted stand-in, recorded in order of use."""

    def build(options: ClaudeAgentOptions) -> ClaudeSDKClient:
        cli = ScriptedCli(frames_per_turn)
        cli_log.append(cli)
        return ClaudeSDKClient(options, transport=cli)

    return ChatSession(SESSION_ID, catalog, a_fetcher(), client_factory=build)


async def stopped_mid_turn(frames: AsyncIterator[str]) -> None:
    """Abandon a live SSE stream the way Starlette abandons a dock that went away mid-turn."""
    streaming = anyio.Event()

    async def consume() -> None:
        async for _ in frames:
            streaming.set()

    async with anyio.create_task_group() as group:
        group.start_soon(consume)
        await streaming.wait()
        group.cancel_scope.cancel()


def spoken_in(frames: list[str]) -> list[str]:
    """Every line of prose an SSE body carried, in order."""
    parsed = [json.loads(frame.removeprefix(DATA_PREFIX).strip()) for frame in frames]
    return [event["text"] for event in parsed if event["type"] == "text"]


async def test_a_stopped_turn_does_not_leave_the_cli_researching(catalog: Catalog) -> None:
    cli_log: list[ScriptedCli] = []
    session = a_session(catalog, cli_log)
    await session.start()

    await stopped_mid_turn(sse_frames(session, FIRST_REQUEST))

    assert cli_log[0].running is False
    await session.aclose()


async def test_the_message_after_a_stop_gets_its_own_answer(catalog: Catalog) -> None:
    cli_log: list[ScriptedCli] = []
    session = a_session(catalog, cli_log)
    await session.start()
    await stopped_mid_turn(sse_frames(session, FIRST_REQUEST))

    answered = [frame async for frame in sse_frames(session, SECOND_REQUEST)]

    spoken = spoken_in(answered)
    assert spoken != []
    assert set(spoken) == {SECOND_REQUEST}
    await session.aclose()


async def test_a_stopped_stream_lets_the_cancellation_through(catalog: Catalog) -> None:
    cli_log: list[ScriptedCli] = []
    session = a_session(catalog, cli_log)
    await session.start()
    frames = sse_frames(session, FIRST_REQUEST)
    await anext(frames)

    with pytest.raises(asyncio.CancelledError):
        await frames.athrow(asyncio.CancelledError)

    assert cli_log[0].running is False
    await session.aclose()


async def test_the_retirement_outlives_the_cancellation_that_triggered_it(catalog: Catalog) -> None:
    """The client is not assumed to shield its own teardown, so the stand-in suspends the way one does."""
    session = ChatSession(SESSION_ID, catalog, a_fetcher(), client_factory=StubClient)
    await session.start()
    retired = session.client
    assert isinstance(retired, StubClient)
    retired.messages = [AssistantMessage(content=[TextBlock(text=line)], model="stub") for line in SPOKEN_LINES]

    await stopped_mid_turn(sse_frames(session, FIRST_REQUEST))

    assert retired.connected is False


async def test_a_dock_closed_rather_than_cancelled_still_retires_the_conversation(catalog: Catalog) -> None:
    """A response task suspended in its own `send` never cancels the generator, it only closes it."""
    cli_log: list[ScriptedCli] = []
    session = a_session(catalog, cli_log)
    await session.start()
    frames = sse_frames(session, FIRST_REQUEST)
    await anext(frames)

    await frames.aclose()

    assert cli_log[0].running is False
    await session.aclose()


async def test_the_message_after_a_close_gets_its_own_answer(catalog: Catalog) -> None:
    cli_log: list[ScriptedCli] = []
    session = a_session(catalog, cli_log)
    await session.start()
    frames = sse_frames(session, FIRST_REQUEST)
    await anext(frames)
    await frames.aclose()

    answered = [frame async for frame in sse_frames(session, SECOND_REQUEST)]

    assert set(spoken_in(answered)) == {SECOND_REQUEST}
    await session.aclose()


async def test_a_turn_longer_than_the_buffer_is_retired_rather_than_wedged(catalog: Catalog) -> None:
    """The abandoned turn's reader is parked mid-buffer, and the retirement has to unpark it."""
    cli_log: list[ScriptedCli] = []
    session = a_session(catalog, cli_log, FRAMES_PAST_THE_BUFFER)
    await session.start()

    with anyio.fail_after(TURN_PATIENCE_SECONDS):
        await stopped_mid_turn(sse_frames(session, FIRST_REQUEST))
        answered = [frame async for frame in sse_frames(session, SECOND_REQUEST)]

    assert cli_log[0].running is False
    assert set(spoken_in(answered)) == {SECOND_REQUEST}
    await session.aclose()
