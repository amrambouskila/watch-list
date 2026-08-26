"""Coordinates reads, writes, caching, and safety guards across the workbook library."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from tv_watchlist.config import Settings
from tv_watchlist.models.catalog_listing import CatalogListing
from tv_watchlist.models.category_create import CategoryCreate
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.category_rename import CategoryRename
from tv_watchlist.models.category_summary import CategorySummary
from tv_watchlist.models.row_change import RowChange
from tv_watchlist.models.row_write import RowWrite
from tv_watchlist.models.shadowed_workbook import ShadowedWorkbook
from tv_watchlist.models.unreadable_workbook import UnreadableWorkbook
from tv_watchlist.services import hero_backup, retirement
from tv_watchlist.workbook import backup, creator, discovery, heroes, reader, renaming, writer
from tv_watchlist.workbook.errors import UnreadableWorkbookError
from tv_watchlist.workbook.freshness import guard_fresh
from tv_watchlist.workbook.locking import is_locked_by_excel, lock_for
from tv_watchlist.workbook.naming import category_id, workbook_filename

_UNREADABLE = (OSError, ValueError, KeyError, TypeError, BadZipFile, InvalidFileException)


class Catalog:
    """Cached, lock-guarded access to every workbook in the library."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[Path, tuple[float, int, CategoryDetail]] = {}

    @property
    def library_dir(self) -> Path:
        return self._settings.library_dir

    def _read_cached(self, path: Path) -> CategoryDetail:
        stat = path.stat()
        key = path.resolve()
        cached = self._cache.get(key)
        if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
        detail = reader.read_category(path)
        self._cache[key] = (stat.st_mtime, stat.st_size, detail)
        return detail

    def _invalidate(self, path: Path) -> None:
        self._cache.pop(path.resolve(), None)

    def _listing(self) -> CatalogListing:
        categories: list[CategorySummary] = []
        unreadable: list[UnreadableWorkbook] = []
        shadowed: list[ShadowedWorkbook] = []
        answering: dict[str, str] = {}
        for path in discovery.workbook_paths(self.library_dir):
            wanted = category_id(path)
            answered_by = answering.get(wanted)
            if answered_by is not None:
                # Reads and writes both go through `discovery.resolve`, which answers with the first
                # of these files; the rest are unreachable, so they are named here instead of
                # quietly becoming a second card for an id only one file can be written to.
                shadowed.append(ShadowedWorkbook(file_name=path.name, category_id=wanted, answered_by=answered_by))
                continue
            # Claimed before the file is opened, because `resolve` picks by name alone: an unreadable
            # file still hides the namesake behind it.
            answering[wanted] = path.name
            try:
                detail = self._read_cached(path)
            except _UNREADABLE as error:
                unreadable.append(UnreadableWorkbook(file_name=path.name, reason=f"{type(error).__name__}: {error}"))
                continue
            summary = detail.model_dump(exclude={"columns", "rows", "reference_sheets"})
            summary["locked_by_excel"] = is_locked_by_excel(path)
            summary["hero_url"] = self._hero_url(detail.id)
            categories.append(CategorySummary(**summary))
        return CatalogListing(
            categories=categories, unreadable=unreadable, shadowed=shadowed, library_dir=str(self.library_dir)
        )

    async def listing(self) -> CatalogListing:
        """Every category in the library."""
        return await asyncio.to_thread(self._listing)

    def _hero_url(self, resolved_id: str) -> str | None:
        for found in heroes.hero_files(self._settings.heroes_dir, resolved_id):
            try:
                # A replacement keeps the filename, so without this stamp the browser goes on
                # painting the artwork it already decoded and never asks for the new bytes.
                stamp = found.stat().st_mtime_ns
            except OSError:
                # A pick being written right now moves the standing image aside between listing the
                # folder and stamping it; the next suffix, or none, is the truth at this instant.
                continue
            return f"/heroes/{found.name}?v={stamp}"
        return None

    def _read_live_lock(self, path: Path) -> CategoryDetail:
        """Cached rows, but the Excel-lock flag and hero image resolved now, not when cached."""
        try:
            detail = self._read_cached(path)
        except _UNREADABLE as error:
            raise UnreadableWorkbookError(f"{path.name} ({type(error).__name__})") from error
        return detail.model_copy(
            update={"locked_by_excel": is_locked_by_excel(path), "hero_url": self._hero_url(detail.id)}
        )

    async def detail(self, wanted_id: str) -> CategoryDetail:
        """One category, with rows and reference sheets, read under the workbook's write lock."""
        path = await asyncio.to_thread(discovery.resolve, self.library_dir, wanted_id)
        async with lock_for(path):
            return await asyncio.to_thread(self._read_live_lock, path)

    def _snapshot(self, path: Path, interval_seconds: float) -> None:
        backup.snapshot(path, self._settings.backup_dir, self._settings.backup_retention, interval_seconds)

    def _mutate(
        self, path: Path, expected_mtime: float, action: Callable[[], None], interval_seconds: float
    ) -> CategoryDetail:
        guard_fresh(path, expected_mtime)
        self._snapshot(path, interval_seconds)
        action()
        self._invalidate(path)
        return self._read_live_lock(path)

    async def _write(
        self,
        wanted_id: str,
        expected_mtime: float,
        action: Callable[[Path], None],
        interval_seconds: float = backup.NO_THROTTLE,
    ) -> CategoryDetail:
        """Snapshots before writing; only a caller that says so lets the throttle reuse an earlier copy."""
        path = await asyncio.to_thread(discovery.resolve, self.library_dir, wanted_id)
        async with lock_for(path):
            return await asyncio.to_thread(self._mutate, path, expected_mtime, lambda: action(path), interval_seconds)

    async def update_row(self, wanted_id: str, row: int, payload: RowWrite) -> CategoryDetail:
        """Set one row's cells and return the reloaded category; the only write the throttle coalesces."""
        cells = payload.sanitized_cells()
        return await self._write(
            wanted_id,
            payload.expected_mtime,
            lambda path: writer.update_row(path, row, cells),
            self._settings.backup_interval_seconds,
        )

    async def append_row(self, wanted_id: str, payload: RowWrite) -> CategoryDetail:
        """Append a row and return the reloaded category."""
        cells = payload.sanitized_cells()
        return await self._write(
            wanted_id, payload.expected_mtime, lambda path: _discard(writer.append_row(path, cells))
        )

    async def delete_row(self, wanted_id: str, row: int, expected_mtime: float) -> CategoryDetail:
        """Delete a row and return the reloaded category."""
        return await self._write(wanted_id, expected_mtime, lambda path: writer.delete_row(path, row))

    async def apply_changes(self, wanted_id: str, changes: list[RowChange], expected_mtime: float) -> CategoryDetail:
        """Apply a whole batch of row changes under one guard, one backup, and one swap."""
        return await self._write(wanted_id, expected_mtime, lambda path: writer.apply_changes(path, changes))

    async def add_watch_column(self, wanted_id: str, expected_mtime: float) -> CategoryDetail:
        """Give a sheet a Watched? column and return the reloaded category."""
        return await self._write(wanted_id, expected_mtime, writer.add_watch_column)

    def _rename(self, path: Path, stem: str, expected_mtime: float) -> CategoryDetail:
        guard_fresh(path, expected_mtime)
        self._snapshot(path, backup.NO_THROTTLE)
        destination = renaming.rename_workbook(path, stem)
        self._carry_artwork(category_id(path), category_id(destination))
        self._invalidate(path)
        self._invalidate(destination)
        return self._read_live_lock(destination)

    def _carry_artwork(self, old_id: str, new_id: str) -> None:
        """A rename changes the id a card looks its image up by, so the image moves with it."""
        if old_id == new_id:
            return
        # Anything already filed under the new id belongs to no category, but it is still artwork.
        hero_backup.retire_heroes(self._settings.heroes_dir, self._settings.backup_dir, new_id)
        heroes.move_heroes(self._settings.heroes_dir, old_id, new_id)

    async def rename_category(self, wanted_id: str, payload: CategoryRename) -> CategoryDetail:
        """Rename the workbook. The category id is derived from the filename, so it changes too."""
        path = await asyncio.to_thread(discovery.resolve, self.library_dir, wanted_id)
        async with lock_for(path):
            return await asyncio.to_thread(self._rename, path, payload.stem, payload.expected_mtime)

    def _retire(self, path: Path, expected_mtime: float) -> None:
        retirement.retire_category(path, self._settings.heroes_dir, self._settings.backup_dir, expected_mtime)
        self._invalidate(path)

    async def retire_category(self, wanted_id: str, expected_mtime: float) -> CatalogListing:
        """Move a category out of the library into the backups folder, and answer with what is left."""
        path = await asyncio.to_thread(discovery.resolve, self.library_dir, wanted_id)
        async with lock_for(path):
            await asyncio.to_thread(self._retire, path, expected_mtime)
        return await self.listing()

    async def create_category(self, payload: CategoryCreate) -> CategoryDetail:
        """Generate a new workbook and return it as a category."""
        destination = self.library_dir / workbook_filename(payload.name)
        async with lock_for(destination):
            path = await asyncio.to_thread(creator.create_category, self.library_dir, payload)
            return await asyncio.to_thread(self._read_live_lock, path)


def _discard(_: int) -> None:
    """Adapt a value-returning writer call to the void action signature."""
