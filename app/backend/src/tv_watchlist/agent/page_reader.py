"""What the fetcher needs from a real browser when the cheap path is blocked."""

from __future__ import annotations

from typing import Protocol


class PageReader(Protocol):
    """Renders a page and hands back its visible text."""

    async def read_text(self, url: str) -> str: ...

    async def aclose(self) -> None: ...
