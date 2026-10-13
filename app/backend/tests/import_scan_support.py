"""Sparse real files for discovery tests, without allocating remux-sized buffers."""

from __future__ import annotations

from pathlib import Path

from tv_watchlist.constants import MEDIA_IMPORT_MIN_BYTES


def media_file(path: Path, size_bytes: int = MEDIA_IMPORT_MIN_BYTES) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.truncate(size_bytes)
    return path
