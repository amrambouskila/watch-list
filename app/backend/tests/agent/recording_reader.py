"""A stand-in for Chromium that records what it was asked to render."""

from __future__ import annotations


class RecordingReader:
    """Satisfies the PageReader protocol without starting a browser."""

    def __init__(self, text: str = "rendered") -> None:
        self.text = text
        self.urls: list[str] = []
        self.closed = False

    async def read_text(self, url: str) -> str:
        self.urls.append(url)
        return self.text

    async def aclose(self) -> None:
        self.closed = True
