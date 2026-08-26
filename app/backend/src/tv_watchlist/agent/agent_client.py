"""What a chat session needs from the SDK client it drives."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from claude_agent_sdk import Message


class AgentClient(Protocol):
    """The `ClaudeSDKClient` surface a session uses, narrow enough to stand in for in tests."""

    async def connect(self, prompt: str | None = None) -> None: ...

    async def query(self, prompt: str, session_id: str = "default") -> None: ...

    def receive_response(self) -> AsyncIterator[Message]: ...

    async def disconnect(self) -> None: ...
