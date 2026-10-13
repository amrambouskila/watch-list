from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from tv_watchlist.models.playback_coverage import PlaybackCoverage


def test_coverage_is_frozen_and_subject_membership_is_immutable() -> None:
    subject = uuid.uuid4()
    coverage = PlaybackCoverage(
        subject_kind="title",
        subject_ids={subject},
        jellyfin_item_id_snapshot=uuid.uuid4(),
        jellyfin_id_snapshot="file",
    )
    assert coverage.subject_ids == frozenset({subject})
    assert coverage.order_type is None and coverage.order_label == ""
    with pytest.raises(ValidationError, match="frozen"):
        coverage.jellyfin_id_snapshot = "replacement"
    with pytest.raises(ValidationError, match="Extra inputs"):
        PlaybackCoverage.model_validate({**coverage.model_dump(), "path": "not evidence"})
