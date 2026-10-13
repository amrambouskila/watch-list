"""Read-only filesystem discovery, run on a worker thread by the import scan."""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from tv_watchlist.constants import IMPORT_SCAN_JOB, MEDIA_IMPORT_EXTENSIONS, MEDIA_IMPORT_MIN_BYTES
from tv_watchlist.data.enums import MediaImportSource
from tv_watchlist.data.errors import ImportPathError
from tv_watchlist.services.import_candidate import ImportCandidate
from tv_watchlist.services.import_naming import assert_within

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class ImportDiscovery:
    """Collect one staging tree's unique media candidates and count refusals without reading content."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.candidates: dict[str, ImportCandidate] = {}
        self.candidates_seen: int = 0
        self.too_small: int = 0
        self.wrong_extension: int = 0
        self.path_refused: int = 0
        self.unreadable: int = 0
        self._observed: set[Path] = set()
        self._refused: set[Path] = set()

    def collect(self, completed_paths: Sequence[Path]) -> None:
        """Prefer the more specific qBittorrent provenance when both arms report the same file."""
        for path in completed_paths:
            self._inspect(path, MediaImportSource.QBITTORRENT_COMPLETED)
        for directory, subdirectories, filenames in os.walk(self.root, followlinks=False, onerror=self._unreadable):
            parent = Path(directory)
            for name in subdirectories:
                path = parent / name
                try:
                    is_link = stat.S_ISLNK(path.lstat().st_mode)
                except OSError as error:
                    self._unreadable(error)
                else:
                    if is_link:
                        self._contained(path)
            for name in filenames:
                self._inspect(parent / name, MediaImportSource.STAGING_FOLDER)

    def _contained(self, path: Path) -> Path | None:
        try:
            return assert_within(path, self.root)
        except ImportPathError:
            if path not in self._refused:
                self._refused.add(path)
                self.path_refused += 1
                _LOGGER.info("import_scan_skipped job=%s path=%r skipped=path_refused", IMPORT_SCAN_JOB, str(path))
        except OSError as error:
            self._unreadable(error)
        return None

    def _inspect(self, path: Path, source: MediaImportSource) -> None:
        resolved = self._contained(path)
        if resolved is None or resolved in self._observed:
            return
        self._observed.add(resolved)
        try:
            observed = resolved.stat()
        except OSError as error:
            self._unreadable(error)
            return
        if not stat.S_ISREG(observed.st_mode):
            return
        self.candidates_seen += 1
        if resolved.suffix.lower() not in MEDIA_IMPORT_EXTENSIONS:
            self.wrong_extension += 1
        elif observed.st_size < MEDIA_IMPORT_MIN_BYTES:
            self.too_small += 1
        else:
            source_path = str(resolved)
            self.candidates[source_path] = ImportCandidate(
                source_path=source_path,
                original_name=resolved.name,
                size_bytes=observed.st_size,
                source=source,
            )

    def _unreadable(self, error: OSError) -> None:
        self.unreadable += 1
        _LOGGER.info(
            "import_scan_skipped job=%s path=%r skipped=unreadable reason=%s",
            IMPORT_SCAN_JOB,
            error.filename,
            type(error).__name__,
        )
