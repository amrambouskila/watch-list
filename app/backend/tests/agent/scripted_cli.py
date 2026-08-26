"""A CLI stand-in at the SDK's own transport seam, so the real client's buffering is under test."""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from typing import Final

import anyio
from anyio.lowlevel import checkpoint
from claude_agent_sdk import Transport

Frame = dict[str, object]

CONTROL_REQUEST: Final[str] = "control_request"
USER_MESSAGE: Final[str] = "user"
SCRIPTED_MODEL: Final[str] = "scripted"
SCRIPTED_SESSION: Final[str] = "scripted-session"


def assistant_says(text: str) -> Frame:
    """One assistant frame carrying a single block of prose."""
    return {
        "type": "assistant",
        "message": {"model": SCRIPTED_MODEL, "content": [{"type": "text", "text": text}]},
    }


def turn_ended(turns: int) -> Frame:
    """The result frame a turn ends on, which is what `receive_response` stops iterating at."""
    return {
        "type": "result",
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": turns,
        "session_id": SCRIPTED_SESSION,
    }


class ScriptedCli(Transport):
    """
    Answers the SDK's control protocol and replies to each question by quoting it back.

    Quoting the question is what lets a test tell one turn's frames from another's: every frame
    the dock receives names the turn it belongs to.
    """

    def __init__(self, prose_frames_per_turn: int) -> None:
        self._prose_frames_per_turn = prose_frames_per_turn
        self._stdout_send, self._stdout_receive = anyio.create_memory_object_stream[Frame](max_buffer_size=math.inf)
        self.turns = 0
        self.closed = False
        self._ready = False

    @property
    def running(self) -> bool:
        """True while this CLI is still a process the backend could be researching on."""
        return self._ready and not self.closed

    async def connect(self) -> None:
        self._ready = True

    async def write(self, data: str) -> None:
        # A real pipe write suspends. Whether a control message's bytes ever leave the backend
        # depends on that suspension, so the stand-in has to suspend too.
        await checkpoint()
        for line in data.splitlines():
            if line.strip():
                self._handle(json.loads(line))

    def read_messages(self) -> AsyncIterator[Frame]:
        return self._stdout_receive.__aiter__()

    async def close(self) -> None:
        self.closed = True
        self._ready = False
        self._stdout_send.close()

    def is_ready(self) -> bool:
        return self._ready

    async def end_input(self) -> None:
        return None

    def _handle(self, message: Frame) -> None:
        if self.closed:
            return
        if message.get("type") == CONTROL_REQUEST:
            self._answer_control(message)
            return
        if message.get("type") == USER_MESSAGE:
            self._answer_question(message)

    def _answer_control(self, message: Frame) -> None:
        self._stdout_send.send_nowait(
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": message.get("request_id"), "response": {}},
            }
        )

    def _answer_question(self, message: Frame) -> None:
        body = message.get("message")
        asked = body["content"] if isinstance(body, dict) else ""
        quoted = str(asked).strip().splitlines()[-1]
        self.turns += 1
        for _ in range(self._prose_frames_per_turn):
            self._stdout_send.send_nowait(assistant_says(quoted))
        self._stdout_send.send_nowait(turn_ended(self.turns))
