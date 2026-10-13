"""The one wall clock the project has, so a test that freezes time knows what it froze."""

from __future__ import annotations

from datetime import UTC, datetime

from tv_watchlist.clock import utcnow


def test_utcnow_is_timezone_aware_and_utc() -> None:
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is UTC


def test_utcnow_moves_forward() -> None:
    first = utcnow()
    second = utcnow()
    assert second >= first
