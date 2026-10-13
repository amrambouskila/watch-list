"""The provider budget is one serialised bucket per upstream, wound by hand so no test ever sleeps."""

from __future__ import annotations

import asyncio

import pytest

from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.constants import TMDB_REQUESTS_PER_SECOND, TVDB_REQUESTS_PER_SECOND

TMDB_DOCUMENTED_CEILING: float = 40.0


class WoundClock:
    """A clock that only moves when its recording sleeper is awaited, so wall time never enters a test."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def read(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_the_bucket_serialises_calls_at_the_configured_rate() -> None:
    clock = WoundClock()
    bucket = TokenBucket(rate_per_second=2.0, burst=1, clock=clock.read, sleep=clock.sleep)

    waits = [await bucket.acquire() for _ in range(3)]

    assert waits == pytest.approx([0.0, 0.5, 0.5])
    assert clock.slept == pytest.approx([0.5, 0.5])
    assert clock.now == pytest.approx(1.0)


async def test_the_bucket_never_sleeps_while_tokens_remain() -> None:
    clock = WoundClock()
    bucket = TokenBucket(rate_per_second=2.0, burst=3, clock=clock.read, sleep=clock.sleep)

    waits = [await bucket.acquire() for _ in range(3)]

    assert sum(waits) == pytest.approx(0.0)
    assert clock.slept == []


async def test_a_bucket_left_alone_refills_only_up_to_its_burst() -> None:
    clock = WoundClock()
    bucket = TokenBucket(rate_per_second=2.0, burst=2, clock=clock.read, sleep=clock.sleep)
    await bucket.acquire()
    await bucket.acquire()

    clock.now = 100.0

    assert [await bucket.acquire() for _ in range(3)] == pytest.approx([0.0, 0.0, 0.5])


async def test_concurrent_callers_queue_instead_of_draining_the_same_token() -> None:
    clock = WoundClock()
    critical_section: list[str] = []

    async def sleeper(seconds: float) -> None:
        critical_section.append("wait-start")
        clock.slept.append(seconds)
        await asyncio.sleep(0)
        clock.now += seconds
        critical_section.append("wait-end")

    bucket = TokenBucket(rate_per_second=2.0, burst=1, clock=clock.read, sleep=sleeper)

    waits = await asyncio.gather(*(bucket.acquire() for _ in range(3)))

    assert waits == pytest.approx([0.0, 0.5, 0.5])
    # Never two waits in flight: the next caller's wait is computed only once the previous one ended.
    assert critical_section == ["wait-start", "wait-end", "wait-start", "wait-end"]


def test_the_tmdb_budget_sits_below_the_documented_limit() -> None:
    assert TMDB_REQUESTS_PER_SECOND < TMDB_DOCUMENTED_CEILING


def test_the_tvdb_budget_is_the_more_conservative_of_the_two() -> None:
    """TheTVDB publishes no limit at all, so its bucket is deliberately the slower one."""
    assert TVDB_REQUESTS_PER_SECOND < TMDB_REQUESTS_PER_SECOND
