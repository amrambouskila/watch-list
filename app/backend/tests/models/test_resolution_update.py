"""`ResolutionUpdate`: the body of one human review decision.

Offline by construction - no database, no provider, no application. What is asserted here is the
boundary: an incoherent decision is refused before anything can act on half of it (CLAUDE.md 10.3, B1).
"""

from __future__ import annotations

from typing import Any, Final, get_args

import pytest
from pydantic import ValidationError

from ts_types import ts_fields, ts_source
from tv_watchlist.constants import MAX_REASON_LENGTH
from tv_watchlist.data.enums import MediaType, UnitKind
from tv_watchlist.models.resolution_update import ResolutionUpdate, ReviewAction

ONE_PIECE: Final[int] = 37854
# `curated_entry.order_type` is String(32); a body that would not fit the column is refused at the edge.
LONGEST_ORDER_TYPE: Final[int] = 32


def test_a_confirm_is_an_action_and_nothing_else() -> None:
    update = ResolutionUpdate(action="confirm")

    assert update.action == "confirm"
    assert update.tmdb_id is None
    assert update.media_type is None
    assert update.note == ""


def test_a_confirm_may_carry_the_reason_a_human_had() -> None:
    """The note is the one field every action shares: it is what the decision is remembered by."""
    update = ResolutionUpdate(action="confirm", note="checked against the box set")

    assert update.note == "checked against the box set"


def test_a_correct_carries_the_title_and_the_span_it_names() -> None:
    update = ResolutionUpdate(
        action="correct",
        media_type=MediaType.TV,
        tmdb_id=ONE_PIECE,
        unit_kind=UnitKind.EPISODES,
        order_type="absolute",
        span_start=19,
        span_end=53,
    )

    assert update.media_type is MediaType.TV
    assert (update.span_start, update.span_end) == (19, 53)


def test_a_reject_carries_only_a_note() -> None:
    update = ResolutionUpdate(action="reject", note="not a film, a making-of featurette")

    assert update.action == "reject"
    assert update.tmdb_id is None


def test_an_order_type_is_an_open_string_never_a_closed_set() -> None:
    """TheTVDB's season types are read at runtime, so one this codebase has never seen must still post."""
    update = ResolutionUpdate(action="correct", media_type=MediaType.TV, tmdb_id=ONE_PIECE, order_type="alttwo")

    assert update.order_type == "alttwo"


@pytest.mark.parametrize(
    "body",
    [
        {"action": "confirm", "tmdb_id": ONE_PIECE},
        {"action": "confirm", "media_type": "tv"},
        {"action": "confirm", "span_start": 1, "span_end": 2},
        {"action": "reject", "tmdb_id": ONE_PIECE},
        {"action": "correct", "media_type": "tv"},
        {"action": "correct", "tmdb_id": ONE_PIECE},
        {"action": "correct", "media_type": "tv", "tmdb_id": ONE_PIECE, "span_start": 53, "span_end": 19},
        {"action": "correct", "media_type": "tv", "tmdb_id": ONE_PIECE, "unknown": "field"},
        {"action": "approve"},
        {"action": "correct", "media_type": "tv", "tmdb_id": 0},
        {"action": "correct", "media_type": "tv", "tmdb_id": ONE_PIECE, "season_number": -1},
        {"action": "correct", "media_type": "tv", "tmdb_id": ONE_PIECE, "order_type": "x" * (LONGEST_ORDER_TYPE + 1)},
        {"action": "confirm", "note": "n" * (MAX_REASON_LENGTH + 1)},
    ],
    ids=[
        "confirm-with-a-title",
        "confirm-with-a-media-type",
        "confirm-with-a-span",
        "reject-with-a-title",
        "correct-without-a-tmdb-id",
        "correct-without-a-media-type",
        "reversed-span",
        "an-unknown-field",
        "an-action-that-is-not-one",
        "a-tmdb-id-below-one",
        "a-negative-season",
        "an-order-type-longer-than-the-column",
        "a-note-longer-than-the-cap",
    ],
)
def test_incoherent_bodies_are_refused(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResolutionUpdate.model_validate(body)


def test_a_season_zero_is_a_season_a_correct_may_name() -> None:
    """Season 0 is the specials bucket and is kept, so `ge=0` and not `ge=1` (CLAUDE.md 5.13)."""
    update = ResolutionUpdate(action="correct", media_type=MediaType.TV, tmdb_id=ONE_PIECE, season_number=0)

    assert update.season_number == 0


def test_the_typescript_mirror_declares_the_same_fields_in_the_same_order() -> None:
    """The contract is written twice; only a test that reads both keeps the two spellings honest."""
    assert ts_fields("ResolutionUpdate") == list(ResolutionUpdate.model_fields)


def test_the_typescript_mirror_spells_every_action_the_backend_accepts() -> None:
    source = ts_source("ResolutionUpdate")

    for action in get_args(ReviewAction):
        assert f'"{action}"' in source
