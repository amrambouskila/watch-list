"""The conditional-request seam a client reads through, and the no-op the unit tests hand it."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from tv_watchlist.clients.response_cache import CachedResponse, NullResponseCache, ResponseCache, ceiling_cutoff
from tv_watchlist.constants import TMDB_CACHE_CEILING_DAYS

A_SOURCE: str = "tmdb"
A_RESOURCE_TYPE: str = "tv"
A_RESOURCE_KEY: str = "37854"


def test_a_cached_response_is_frozen_and_slotted() -> None:
    cached = CachedResponse(
        etag='W/"abc"', last_modified="Mon, 15 Sep 2026 00:00:00 GMT", payload_digest="d" * 64, last_success_at=None
    )
    assert dataclasses.is_dataclass(cached)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cached.etag = "changed"
    assert not hasattr(cached, "__dict__")


def test_every_field_of_a_cached_response_may_be_unknown() -> None:
    cached = CachedResponse(etag=None, last_modified=None, payload_digest=None, last_success_at=None)
    assert (cached.etag, cached.last_modified, cached.payload_digest, cached.last_success_at) == (
        None,
        None,
        None,
        None,
    )


def test_a_cached_response_carries_a_timezone_aware_success_stamp() -> None:
    stamped = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    assert CachedResponse(None, None, None, stamped).last_success_at == stamped


def test_the_cutoff_is_the_oldest_success_the_caching_term_still_allows() -> None:
    """One definition, imported by the client that renews on it and by the cursor that lists on it.

    It lives here rather than in either caller because `clients/` and `ingest/` both already import this
    module, and two arithmetics for one licence term is how they come to disagree.
    """
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    assert ceiling_cutoff(now, TMDB_CACHE_CEILING_DAYS) == now - timedelta(days=TMDB_CACHE_CEILING_DAYS)


def test_the_null_cache_satisfies_the_seam_it_stands_in_for() -> None:
    # `isinstance` against a runtime_checkable Protocol checks method presence only, never signatures;
    # `test_the_null_cache_never_remembers_anything` calls all three through to cover those.
    assert isinstance(NullResponseCache(), ResponseCache)


async def test_the_null_cache_never_remembers_anything() -> None:
    cache = NullResponseCache()
    await cache.store(
        A_SOURCE, A_RESOURCE_TYPE, A_RESOURCE_KEY, etag='W/"abc"', last_modified=None, payload_digest="d" * 64
    )
    await cache.record_failure(A_SOURCE, A_RESOURCE_TYPE, A_RESOURCE_KEY, "connect timeout")

    assert await cache.lookup(A_SOURCE, A_RESOURCE_TYPE, A_RESOURCE_KEY) is None
