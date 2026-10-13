from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from tv_watchlist.models.playback_occurrence import PlaybackOccurrence


def test_occurrence_has_exact_frozen_json_contract() -> None:
    value = PlaybackOccurrence(
        entry_id=uuid.uuid4(),
        subject_kind="episode",
        subject_id_snapshot=uuid.uuid4(),
        tmdb_key="tv:1399:s2:e5",
        position_in_entry=2,
    )
    assert list(type(value).model_fields) == [
        "entry_id",
        "subject_kind",
        "subject_id_snapshot",
        "tmdb_key",
        "position_in_entry",
    ]
    assert PlaybackOccurrence.model_validate(value.model_dump(mode="json")) == value
    with pytest.raises(ValidationError, match="frozen"):
        value.position_in_entry = 3


@pytest.mark.parametrize(
    "change",
    [
        {"position_in_entry": 0},
        {"position_in_entry": -1},
        {"position_in_entry": True},
        {"subject_kind": "curated_entry"},
        {"tmdb_key": "x" * 65},
        {"unapproved": True},
    ],
)
def test_invalid_occurrence_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PlaybackOccurrence.model_validate(
            {
                "entry_id": uuid.uuid4(),
                "subject_kind": "title",
                "subject_id_snapshot": uuid.uuid4(),
                "tmdb_key": None,
                "position_in_entry": 1,
                **change,
            }
        )
