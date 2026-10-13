"""Discovery counts are frozen and nonnegative, with no identification fields without a producer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.models.import_scan_result import ImportScanResult

COUNTS: tuple[str, ...] = (
    "candidates_seen",
    "found",
    "already_known",
    "too_small",
    "wrong_extension",
    "qbittorrent_outside_staging",
    "path_refused",
    "unreadable",
)


def test_import_scan_result_is_frozen_and_has_only_discovery_fields() -> None:
    result = ImportScanResult.model_validate(
        {"staging_dir": "", "qbittorrent_reachable": False} | dict.fromkeys(COUNTS, 0)
    )

    assert set(ImportScanResult.model_fields) == {*COUNTS, "staging_dir", "qbittorrent_reachable"}
    with pytest.raises(ValidationError, match="frozen"):
        result.found = 1


@pytest.mark.parametrize("name", COUNTS, ids=str)
def test_import_scan_counts_cannot_be_negative(name: str) -> None:
    with pytest.raises(ValidationError, match=name):
        ImportScanResult.model_validate(
            {"staging_dir": "", "qbittorrent_reachable": False} | dict.fromkeys(COUNTS, 0) | {name: -1}
        )
