from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from ts_types import ts_fields
from tv_watchlist.models.position_write import PositionWrite


def test_position_write_matches_the_exact_typescript_contract() -> None:
    assert list(PositionWrite.model_fields) == ts_fields("PositionWrite") == ["watch_event_id", "expected_mtime"]
    event_id = uuid.uuid4()
    body = PositionWrite(watch_event_id=event_id, expected_mtime=123.25)
    assert body.watch_event_id == event_id
    assert body.expected_mtime == pytest.approx(123.25)


@pytest.mark.parametrize(
    "bad",
    [
        {"position_seconds": 1},
        {"expected_mtime": float("nan")},
        {"expected_mtime": float("inf")},
        {"watch_event_id": "not-a-uuid"},
    ],
)
def test_position_write_refuses_arbitrary_values_and_nonfinite_stamps(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PositionWrite.model_validate({"watch_event_id": str(uuid.uuid4()), "expected_mtime": 123.25} | bad)
