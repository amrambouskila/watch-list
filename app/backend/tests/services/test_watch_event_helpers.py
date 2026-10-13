"""The parts of the watch-log service that need no database: the key grammar, the stamp, the guard.

Separated from tests/services/test_watch_events_service.py deliberately. Everything there is a real
Postgres and skips without one; everything here is a pure function or a failure path that can be
provoked with no server at all, so it runs on every machine and on every CI job.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final, Self

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.config import Settings
from tv_watchlist.data.enums import MediaType, WatchSubjectKind
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.mirror_outcome import DEFERRED
from tv_watchlist.services.watch_events import (
    _episode_key,
    _named,
    _occurred,
    _work_key,
    mirror_recorded_entry,
)

NOW: Final[datetime] = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
A_STAMP: Final[datetime] = datetime(2026, 9, 20, 14, 0, tzinfo=UTC)
ONE_PIECE_TMDB_ID: Final[int] = 37854
LABOON_SEASON: Final[int] = 2
LABOON_EPISODE: Final[int] = 62
LABOON_KEY: Final[str] = "tv:37854:s2:e62"
FIGHT_CLUB_TMDB_ID: Final[int] = 550
AN_EASTERN_OFFSET: Final[timezone] = timezone(timedelta(hours=3))
SERVICE_LOGGER: Final[str] = "tv_watchlist.services.watch_events"


def _clock() -> datetime:
    return NOW


class _ASessionThatFails:
    """A session that cannot reach a database: every statement raises, as a lost connection would."""

    def __init__(self) -> None:
        self._session = AsyncSession()

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401  # a passthrough is as typed as what it wraps
        return getattr(self._session, name)


class _AFactoryOfFailingSessions:
    """A session factory handing back a session whose statements raise, the task's worst case."""

    def __call__(self) -> Self:
        return self

    async def __aenter__(self) -> _ASessionThatFails:
        return _ASessionThatFails()

    async def __aexit__(self, *_: object) -> None:
        return None


# -- the tmdb pointer --------------------------------------------------------------------------------


def test_an_episode_key_is_the_titles_id_with_the_episodes_own_bucketed_numbers() -> None:
    """The reference value: TMDB buckets One Piece absolutely, so Laboon is s2e62, not s1e62."""
    assert _episode_key(MediaType.TV, ONE_PIECE_TMDB_ID, LABOON_SEASON, LABOON_EPISODE) == LABOON_KEY


def test_an_episode_of_a_title_with_no_provider_match_has_no_key() -> None:
    """`Title.tmdb_id` is nullable on purpose, and a pointer nobody can follow is worse than none."""
    assert _episode_key(MediaType.TV, None, LABOON_SEASON, LABOON_EPISODE) is None


def test_a_work_key_names_the_media_type_and_the_id() -> None:
    assert _work_key(MediaType.MOVIE, FIGHT_CLUB_TMDB_ID) == f"movie:{FIGHT_CLUB_TMDB_ID}"
    assert _work_key(MediaType.TV, ONE_PIECE_TMDB_ID) == f"tv:{ONE_PIECE_TMDB_ID}"


@pytest.mark.parametrize(
    ("media_type", "tmdb_id"),
    [(None, FIGHT_CLUB_TMDB_ID), (MediaType.MOVIE, None), (None, None)],
    ids=["entry-the-resolver-has-not-matched", "title-with-no-provider-id", "neither"],
)
def test_a_work_with_nothing_to_point_at_has_no_key(media_type: MediaType | None, tmdb_id: int | None) -> None:
    assert _work_key(media_type, tmdb_id) is None


# -- the stamp ---------------------------------------------------------------------------------------


def test_an_absent_stamp_is_now() -> None:
    assert _occurred(None, _clock) == NOW


def test_an_aware_stamp_is_kept_exactly_as_given() -> None:
    """A player or Jellyfin report may arrive long after the thing it describes."""
    eastern = A_STAMP.astimezone(AN_EASTERN_OFFSET)

    kept = _occurred(eastern, _clock)

    assert kept == A_STAMP
    assert kept.utcoffset() == AN_EASTERN_OFFSET.utcoffset(None)


def test_a_naive_stamp_is_read_as_utc_rather_than_guessed_at() -> None:
    """The column is `timestamptz`; a naive value would leave asyncpg guessing a zone."""
    read = _occurred(A_STAMP.replace(tzinfo=None), _clock)

    assert read.tzinfo is not None
    assert read == A_STAMP


# -- what the 404 says -------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(WatchSubjectKind), ids=[kind.value for kind in WatchSubjectKind])
def test_the_refusal_names_the_kind_and_the_id_it_was_given(kind: WatchSubjectKind) -> None:
    """`_MESSAGE_BY_ERROR` wraps this as "No {detail} to record a watch event against."."""
    subject_id = uuid.uuid4()

    assert _named(kind, subject_id) == f"{kind.value} {subject_id}"


# -- the fire-and-forget task ------------------------------------------------------------------------


async def test_a_session_that_cannot_reach_the_database_is_logged_not_raised(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """The response has already been sent, so nothing here may escape as an ASGI traceback."""
    with caplog.at_level(logging.ERROR, logger=SERVICE_LOGGER):
        outcome = await mirror_recorded_entry(
            _AFactoryOfFailingSessions(), Catalog(settings), uuid.uuid4(), clock=_clock
        )

    assert outcome == DEFERRED
    assert "watch_event_mirror_crashed" in caplog.text
    # `exception` rather than `warning`: an unexpected failure keeps its traceback.
    assert any(record.exc_info is not None for record in caplog.records)
