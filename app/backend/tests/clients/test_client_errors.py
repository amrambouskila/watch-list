"""Every provider failure is one hierarchy, so an ingest can catch the base and record the detail."""

from __future__ import annotations

import pytest

from tv_watchlist.clients.errors import (
    OutboundUrlError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderResponseTooLargeError,
    ProviderUnavailableError,
    UnknownSeasonTypeError,
)


@pytest.mark.parametrize(
    "error_class",
    [
        ProviderNotConfiguredError,
        OutboundUrlError,
        ProviderResponseTooLargeError,
        ProviderUnavailableError,
        ProviderRefusedError,
        ProviderNotFoundError,
        UnknownSeasonTypeError,
    ],
)
def test_every_provider_error_subclasses_provider_error(error_class: type[ProviderError]) -> None:
    assert issubclass(error_class, ProviderError)


@pytest.mark.parametrize("retry_after", [None, 30.0])
def test_a_refusal_carries_the_upstreams_retry_hint(retry_after: float | None) -> None:
    error = ProviderRefusedError("tmdb answered 429", retry_after=retry_after)
    assert error.retry_after == retry_after
    assert str(error) == "tmdb answered 429"


def test_a_refusal_without_a_hint_still_reads_as_no_hint() -> None:
    assert ProviderRefusedError("tmdb answered 401").retry_after is None
