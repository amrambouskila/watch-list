"""The filename parser's frozen, bounded internal result."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.models.filename_parse import FilenameParse


def test_a_refusal_is_empty_and_frozen() -> None:
    result = FilenameParse()
    assert result.model_dump() == {
        "series_token": "",
        "year": None,
        "season_number": None,
        "episode_number": None,
        "absolute_number": None,
        "confidence": 0,
    }
    with pytest.raises(ValidationError, match="frozen_instance"):
        result.confidence = 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("season_number", -1), ("episode_number", -1), ("absolute_number", 0), ("confidence", -1), ("confidence", 2)],
)
def test_invalid_numbering_and_confidence_are_refused(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        FilenameParse.model_validate({field: value})
