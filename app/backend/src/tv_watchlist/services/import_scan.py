"""Discover the owner's staged media without identifying, moving, hashing or opening a workbook."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.errors import ProviderError
from tv_watchlist.clients.qbittorrent_client import QbittorrentClient
from tv_watchlist.clients.transport import elapsed_ms_since
from tv_watchlist.config import Settings
from tv_watchlist.constants import IMPORT_SCAN_ADVISORY_LOCK_KEY, IMPORT_SCAN_JOB, MEDIA_IMPORT_LOOKUP_BATCH_SIZE
from tv_watchlist.data.enums import MediaImportStatus
from tv_watchlist.data.errors import ImportPathError
from tv_watchlist.data.models.media_import import MediaImport
from tv_watchlist.models.import_scan_result import ImportScanResult
from tv_watchlist.services.import_discovery import ImportDiscovery
from tv_watchlist.services.import_naming import assert_within

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_ADVISORY_LOCK: Final = text("SELECT pg_advisory_xact_lock(:key)")


async def scan(
    session: AsyncSession,
    settings: Settings,
    *,
    qbittorrent: QbittorrentClient | None,
) -> ImportScanResult:
    """Create only new `found` rows; the caller owns commit and rollback, including the scan lock."""
    started = time.monotonic()
    staging_dir = settings.import_staging_dir
    _LOGGER.info("import_scan job=%s staging_dir=%r outcome=started", IMPORT_SCAN_JOB, str(staging_dir or ""))
    # A process lock ends before the caller commits; the next session could still see no rows then.
    await session.execute(_ADVISORY_LOCK, {"key": IMPORT_SCAN_ADVISORY_LOCK_KEY})
    discovery = ImportDiscovery(staging_dir or Path())
    reachable = False
    outside_staging = 0
    if staging_dir is not None:
        try:
            root = await asyncio.to_thread(staging_dir.resolve)
        except (OSError, ValueError) as error:
            discovery.unreadable += 1
            _LOGGER.info(
                "import_scan_skipped job=%s skipped=unreadable reason=%s", IMPORT_SCAN_JOB, type(error).__name__
            )
        else:
            completed_paths, outside_staging, reachable = await _completed_paths(root, qbittorrent)
            discovery = ImportDiscovery(root)
            await asyncio.to_thread(discovery.collect, completed_paths)
    paths = list(discovery.candidates)
    known: set[str] = set()
    for start in range(0, len(paths), MEDIA_IMPORT_LOOKUP_BATCH_SIZE):
        known.update(
            await session.scalars(
                select(MediaImport.source_path).where(
                    MediaImport.source_path.in_(paths[start : start + MEDIA_IMPORT_LOOKUP_BATCH_SIZE]),
                    MediaImport.superseded_at.is_(None),
                    MediaImport.status != MediaImportStatus.FAILED,
                )
            )
        )
    session.add_all(
        MediaImport(
            source=candidate.source,
            source_path=candidate.source_path,
            original_name=candidate.original_name,
            size_bytes=candidate.size_bytes,
            status=MediaImportStatus.FOUND,
        )
        for path, candidate in discovery.candidates.items()
        if path not in known
    )
    await session.flush()
    result = ImportScanResult(
        staging_dir=str(discovery.root) if staging_dir is not None else "",
        candidates_seen=discovery.candidates_seen,
        found=len(paths) - len(known),
        already_known=len(known),
        too_small=discovery.too_small,
        wrong_extension=discovery.wrong_extension,
        qbittorrent_reachable=reachable,
        qbittorrent_outside_staging=outside_staging,
        path_refused=discovery.path_refused,
        unreadable=discovery.unreadable,
    )
    _LOGGER.info(
        "import_scan job=%s staging_dir=%r candidates_seen=%d found=%d already_known=%d too_small=%d "
        "wrong_extension=%d qbittorrent_reachable=%s qbittorrent_outside_staging=%d path_refused=%d "
        "unreadable=%d elapsed_ms=%d outcome=finished",
        IMPORT_SCAN_JOB,
        result.staging_dir,
        result.candidates_seen,
        result.found,
        result.already_known,
        result.too_small,
        result.wrong_extension,
        result.qbittorrent_reachable,
        result.qbittorrent_outside_staging,
        result.path_refused,
        result.unreadable,
        elapsed_ms_since(started),
    )
    return result


async def _completed_paths(root: Path, client: QbittorrentClient | None) -> tuple[list[Path], int, bool]:
    if client is None or not client.configured:
        return [], 0, False
    paths: list[Path] = []
    outside_staging = 0
    try:
        for torrent in await client.completed_torrents():
            if not torrent.has_recognised_hash:
                _LOGGER.info("import_scan_skipped job=%s skipped=unrecognised_hash", IMPORT_SCAN_JOB)
                continue
            save_path = Path(torrent.save_path)
            if not await asyncio.to_thread(_is_staging_directory, save_path, root):
                outside_staging += 1
                continue
            paths.extend(file.absolute_path(save_path) for file in await client.torrent_files(torrent.hash))
    except ProviderError as error:
        _LOGGER.info(
            "import_scan_skipped job=%s skipped=qbittorrent_unreachable reason=%s",
            IMPORT_SCAN_JOB,
            type(error).__name__,
        )
        return [], outside_staging, False
    return paths, outside_staging, True


def _is_staging_directory(path: Path, root: Path) -> bool:
    try:
        if not path.is_absolute():
            return False
        if path.resolve() == root:
            return True
        assert_within(path, root)
    except (ImportPathError, OSError, ValueError):
        return False
    return True
