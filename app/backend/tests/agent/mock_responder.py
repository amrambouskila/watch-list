"""An httpx transport that answers with canned responses and records what was requested."""

from __future__ import annotations

import httpx


class MockResponder:
    """Answers successive requests with successive responses, repeating the last one."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._remaining = list(responses)
        self.requested: list[str] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requested.append(str(request.url))
        return self._remaining.pop(0) if len(self._remaining) > 1 else self._remaining[0]
