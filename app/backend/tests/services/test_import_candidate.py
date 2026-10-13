"""A discovered candidate is an immutable, typed filesystem observation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from tv_watchlist.constants import MEDIA_IMPORT_MIN_BYTES
from tv_watchlist.data.enums import MediaImportSource
from tv_watchlist.services.import_candidate import ImportCandidate


def test_import_candidates_are_frozen() -> None:
    candidate = ImportCandidate(
        "/staging/film.mkv", "film.mkv", MEDIA_IMPORT_MIN_BYTES, MediaImportSource.STAGING_FOLDER
    )

    with pytest.raises(FrozenInstanceError):
        setattr(candidate, "size_bytes", 0)
