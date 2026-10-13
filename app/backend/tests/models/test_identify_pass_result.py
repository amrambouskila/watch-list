"""Identification counts never leak into the discovery result."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.models.identify_pass_result import IdentifyPassResult
from tv_watchlist.models.import_scan_result import ImportScanResult


def test_counts_default_to_zero_and_are_frozen() -> None:
    result = IdentifyPassResult()
    assert result.model_dump() == {"identified": 0, "unidentified": 0}
    assert set(IdentifyPassResult.model_fields).isdisjoint(ImportScanResult.model_fields)
    with pytest.raises(ValidationError, match="frozen_instance"):
        result.identified = 1


@pytest.mark.parametrize("field", ["identified", "unidentified"])
def test_negative_counts_are_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        IdentifyPassResult.model_validate({field: -1})
