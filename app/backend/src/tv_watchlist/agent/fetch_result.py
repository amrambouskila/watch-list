"""What one URL fetch produced, and which path produced it."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel

CHEAP_TRANSPORT: Final = "httpx"
BROWSER_TRANSPORT: Final = "chromium"
FetchTransport = Literal[CHEAP_TRANSPORT, BROWSER_TRANSPORT]


class FetchResult(BaseModel):
    """Readable page text, the path that read it, and whether it hit the size cap."""

    text: str
    via: FetchTransport
    truncated: bool
