from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import anyio
import httpx

from provider_fixtures import A_RECORDED_JELLYFIN_KEY


class PlaybackStream(httpx.AsyncByteStream):
    """Count upstream production and expose a cancellation checkpoint without accumulating bytes."""

    def __init__(
        self, *, count: int = 3, fail_at: int | None = None, block_at: int | None = None, fail_close: bool = False
    ) -> None:
        self.count = count
        self.fail_at = fail_at
        self.block_at = block_at
        self.fail_close = fail_close
        self.produced = 0
        self.closed = False
        self.waiting = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index in range(self.count):
            if index == self.block_at:
                self.waiting.set()
                await asyncio.Event().wait()
            if index == self.fail_at:
                raise httpx.ReadError(f"upstream revealed {A_RECORDED_JELLYFIN_KEY}")
            self.produced += 1
            yield b"frame"

    async def aclose(self) -> None:
        await anyio.sleep(0)
        self.closed = True
        if self.fail_close:
            raise httpx.ReadError(f"cleanup revealed {A_RECORDED_JELLYFIN_KEY}")
