"""A ClaudeSDKClient stand-in: no CLI subprocess, no model call, scripted messages."""

from __future__ import annotations

from collections.abc import AsyncIterator

from anyio.lowlevel import checkpoint
from claude_agent_sdk import ClaudeAgentOptions, Message


class StubClient:
    """Replays a scripted message list and records everything the session asked of it."""

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.messages: list[Message] = []
        self.prompts: list[str] = []
        self.connected = False

    async def connect(self, prompt: str | None = None) -> None:
        self.connected = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Message]:
        for message in self.messages:
            # Both suspensions are the ones a real client makes, and a turn abandoned mid-stream
            # turns entirely on whether the work after them still happens.
            await checkpoint()
            yield message

    async def disconnect(self) -> None:
        await checkpoint()
        self.connected = False
