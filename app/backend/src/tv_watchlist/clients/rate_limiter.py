"""One serialised token bucket per upstream, so concurrent callers queue rather than fan out at it."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class TokenBucket:
    """`burst` tokens refilling at `rate_per_second`, handed out one call at a time."""

    def __init__(
        self,
        rate_per_second: float,
        burst: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rate = rate_per_second
        self._burst = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(burst)
        self._updated_at = clock()
        # The whole take - including the wait - is under one lock, which is what makes this a single
        # worker per upstream instead of every caller computing the same wait from the same tokens.
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Take one token, waiting for it when the bucket is empty; returns the seconds waited."""
        async with self._lock:
            self._refill()
            waited = 0.0
            if self._tokens < 1.0:
                waited = (1.0 - self._tokens) / self._rate
                await self._sleep(waited)
                self._refill()
            self._tokens -= 1.0
            return waited

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._updated_at) * self._rate)
        self._updated_at = now
