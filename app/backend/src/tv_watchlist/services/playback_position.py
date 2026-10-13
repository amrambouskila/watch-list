from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import WatchEventKind, WatchEventSource
from tv_watchlist.data.errors import PlaybackStateError
from tv_watchlist.data.models import CuratedEntry, CuratedEntryItem, WatchEvent
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.locked_curated_entry import locked_curated_entry
from tv_watchlist.services.watch_mirror import (
    entry_watch_states,
    pending_mirror_cells,
    record_mirrored,
    writable_mirror_cells,
)
from tv_watchlist.workbook.errors import StaleWorkbookError
from tv_watchlist.workbook.freshness import MTIME_TOLERANCE_SECONDS
from tv_watchlist.workbook.reader import WorkbookProjection
from tv_watchlist.workbook.schema import watch_column


async def project_playback_position(
    session: AsyncSession, catalog: Catalog, entry_id: uuid.UUID, event_id: uuid.UUID, *, expected_mtime: float
) -> CategoryDetail:
    """Project a committed current snapshot through one guarded Position-and-Watched workbook write."""
    entry, category = await locked_curated_entry(session, entry_id)
    event = await _current_event(session, entry, event_id)
    affected = list(
        await session.scalars(
            select(CuratedEntry).where(CuratedEntry.category_id == category.id, CuratedEntry.removed_at.is_(None))
        )
    )
    states = await entry_watch_states(session, category.id)
    before = await catalog.projection(category.slug)
    if abs(before.detail.mtime - expected_mtime) > MTIME_TOLERANCE_SECONDS:
        raise StaleWorkbookError(before.detail.file_name)
    selected_row = _row_for(before, entry.id)
    pending, cells = _watch_cells(before, affected, states)
    seconds = cast(int, event.position_seconds)
    try:
        written = await catalog.apply_position_writeback(category.slug, {selected_row: seconds}, cells, expected_mtime)
    except StaleWorkbookError:
        fresh = await catalog.projection(category.slug)
        _unchanged(before, fresh, selected_row, cells)
        written = await catalog.apply_position_writeback(
            category.slug, {selected_row: seconds}, cells, fresh.detail.mtime
        )
    record_mirrored(affected, pending)
    for changed in affected:
        if changed.id in pending:
            changed.observed_watch_cell = pending[changed.id]
    category.workbook_mtime = written.mtime
    category.last_mirrored_at = utcnow()
    return written


async def _current_event(session: AsyncSession, entry: CuratedEntry, event_id: uuid.UUID) -> WatchEvent:
    event = await session.get(WatchEvent, event_id)
    if event is None or event.source is not WatchEventSource.PLAYER or event.category_id != entry.category_id:
        raise PlaybackStateError("That player event does not belong to this workbook.")
    slots = select(CuratedEntryItem).where(CuratedEntryItem.curated_entry_id == entry.id)
    episode_ids = slots.with_only_columns(CuratedEntryItem.episode_id)
    movie_ids = slots.with_only_columns(CuratedEntryItem.movie_title_id)
    subject = or_(WatchEvent.episode_id.in_(episode_ids), WatchEvent.title_id.in_(movie_ids))
    belongs = await session.scalar(select(WatchEvent.id).where(WatchEvent.id == event_id, subject))
    if belongs is None or event.kind not in (WatchEventKind.PROGRESSED, WatchEventKind.COMPLETED):
        raise PlaybackStateError("That player event does not describe a current slot in this entry.")
    if event.position_seconds is None:
        raise PlaybackStateError("The saved event has no playback position.")
    return (
        await session.execute(
            select(WatchEvent)
            .where(
                subject,
                WatchEvent.source == WatchEventSource.PLAYER,
                WatchEvent.category_id == entry.category_id,
                WatchEvent.kind.in_((WatchEventKind.PROGRESSED, WatchEventKind.COMPLETED)),
                WatchEvent.position_seconds.is_not(None),
            )
            .order_by(WatchEvent.occurred_at.desc(), WatchEvent.recorded_at.desc(), WatchEvent.id.desc())
            .limit(1)
        )
    ).scalar_one()


def _row_for(projection: WorkbookProjection, entry_id: uuid.UUID) -> int:
    matches = [row for row, value in projection.row_ids.items() if value == str(entry_id)]
    if len(matches) != 1:
        raise StaleWorkbookError(projection.detail.file_name)
    return matches[0]


def _watch_cells(
    projection: WorkbookProjection, entries: Sequence[CuratedEntry], states: Mapping[uuid.UUID, WatchEventKind]
) -> tuple[dict[uuid.UUID, str], dict[int, dict[str, str]]]:
    column = watch_column(projection.detail.columns)
    if column is None:
        return {}, {}
    pending = writable_mirror_cells(pending_mirror_cells(entries, states), column, category=projection.detail.id)
    rows = {row.row: row.cells for row in projection.detail.rows}
    safe: dict[uuid.UUID, str] = {}
    cells: dict[int, dict[str, str]] = {}
    for entry in entries:
        if entry.id not in pending:
            continue
        row = _row_for(projection, entry.id)
        if rows[row].get(column.key, "").strip() != (entry.mirrored_watch_cell or "").strip():
            continue
        safe[entry.id] = pending[entry.id]
        cells[row] = {column.key: pending[entry.id]}
    return safe, cells


def _unchanged(
    before: WorkbookProjection, fresh: WorkbookProjection, selected_row: int, cells: Mapping[int, Mapping[str, str]]
) -> None:
    before_rows = {row.row: row.cells for row in before.detail.rows}
    fresh_rows = {row.row: row.cells for row in fresh.detail.rows}
    for row in {*cells, selected_row}:
        identity = before.row_ids[row]
        if fresh.row_ids.get(row) != identity or list(fresh.row_ids.values()).count(identity) != 1:
            raise StaleWorkbookError(fresh.detail.file_name)
        for key in cells.get(row, {}):
            if fresh_rows.get(row, {}).get(key) != before_rows[row].get(key):
                raise StaleWorkbookError(fresh.detail.file_name)
    if fresh.position_values.get(selected_row, "") != before.position_values.get(selected_row, ""):
        raise StaleWorkbookError(fresh.detail.file_name)
