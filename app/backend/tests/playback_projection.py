from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from episode_join_support import a_series_file, a_show, an_episode_file, file_id
from mirror_support import Projected, category_row, entries_for
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.enums import ResolutionState, UnitKind, WatchEventKind, WatchSubjectKind
from tv_watchlist.data.models import CuratedEntryItem, JellyfinItem
from tv_watchlist.ingest.expansion import rebuild_items
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.schema import watch_column


class PlaybackProjection(Projected):
    """A real copied workbook whose first three rows cover a single three-episode file."""

    file: JellyfinItem
    episode_ids: list[uuid.UUID]

    def snapshot(
        self,
        *,
        selected: int = 1,
        seconds: int = 60,
        kind: WatchEventKind = WatchEventKind.PROGRESSED,
        occurred_at: datetime | None = None,
    ) -> WatchEventCreate:
        return WatchEventCreate(
            subject_kind=WatchSubjectKind.EPISODE,
            subject_id=self.episode_ids[selected],
            kind=kind,
            occurred_at=occurred_at,
            position_seconds=seconds,
            runtime_seconds=300,
        )

    @classmethod
    async def create(cls, session: AsyncSession, catalog: Catalog, path: Path) -> PlaybackProjection:
        detail = read_category(path)
        column = watch_column(detail.columns)
        assert column is not None
        category = category_row(detail, uuid.uuid4())
        entries = entries_for(category.id, 3, path=path)
        title = await a_show(session, "A playback show", episodes=3, tmdb_id=999)
        for number, entry in enumerate(entries, start=1):
            entry.title_id = title.id
            entry.unit_kind = UnitKind.EPISODES
            entry.resolution_state = ResolutionState.CONFIRMED
            entry.order_type = "aired"
            entry.span_start = entry.span_end = number
        session.add(category)
        session.add_all(entries)
        await session.flush()
        await rebuild_items(session, category.id)
        series = await a_series_file(session, jellyfin_id=file_id(100), name=title.name, tmdb_id=title.tmdb_id)
        file = await an_episode_file(session, series_jellyfin_id=series.jellyfin_id, season=1, number=1, number_end=3)
        written = await catalog.write_row_ids(
            category.slug,
            {entry.sheet_row: str(entry.id) for entry in entries if entry.sheet_row is not None},
            detail.mtime,
        )
        category.workbook_mtime = written.mtime
        await session.flush()
        result = cls(path, category, entries, column.key)
        result.file = file
        result.episode_ids = list(
            await session.scalars(
                select(CuratedEntryItem.episode_id)
                .where(CuratedEntryItem.category_id == category.id)
                .order_by(CuratedEntryItem.absolute_position)
            )
        )
        return result
