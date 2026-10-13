"""A filesystem observation safe to project as an import's initial provenance."""

from __future__ import annotations

from dataclasses import dataclass

from tv_watchlist.data.enums import MediaImportSource


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    """A contained regular file; size is the local filesystem's byte count, not a peer's claim."""

    source_path: str
    original_name: str
    size_bytes: int
    source: MediaImportSource
