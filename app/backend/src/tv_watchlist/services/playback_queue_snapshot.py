from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, Episode, EpisodeOrder, Title
from tv_watchlist.ingest.expansion import numberings_for
from tv_watchlist.models.playback_occurrence import PlaybackOccurrence
from tv_watchlist.models.playback_queue_snapshot import PlaybackQueueSnapshot
from tv_watchlist.services.tmdb_key import tmdb_key


async def capture_playback_queue(
    session: AsyncSession,
    category_id: uuid.UUID,
    subject_kind: Literal["episode", "title"],
    subject_ids: frozenset[uuid.UUID],
) -> PlaybackQueueSnapshot:
    """Capture fresh logical curation and actual numbering in at most two column queries."""
    entry_title, subject_title = aliased(Title), aliased(Title)
    entry_columns = (
        CuratedEntry.id,
        CuratedEntry.position,
        CuratedEntry.resolution_state,
        CuratedEntry.title_id,
        CuratedEntry.unit_kind,
        CuratedEntry.order_type,
        CuratedEntry.order_label,
        CuratedEntry.span_start,
        CuratedEntry.span_end,
        CuratedEntry.season_number,
        CuratedEntry.raw_title,
        CuratedEntry.raw_unit,
        CuratedEntry.raw_release,
    )
    rows = (
        await session.execute(
            select(
                *entry_columns,
                entry_title.media_type.label("title_media_type"),
                entry_title.tmdb_id.label("title_tmdb_id"),
                CuratedEntryItem.episode_id,
                CuratedEntryItem.movie_title_id,
                CuratedEntryItem.position_in_entry,
                subject_title.media_type.label("subject_media_type"),
                subject_title.tmdb_id.label("subject_tmdb_id"),
                Episode.season_number.label("episode_season"),
                Episode.episode_number,
            )
            .select_from(CuratedEntry)
            .join(Category, Category.id == CuratedEntry.category_id)
            .outerjoin(entry_title, entry_title.id == CuratedEntry.title_id)
            .outerjoin(
                CuratedEntryItem,
                and_(
                    CuratedEntryItem.curated_entry_id == CuratedEntry.id,
                    CuratedEntryItem.category_id == category_id,
                ),
            )
            .outerjoin(Episode, Episode.id == CuratedEntryItem.episode_id)
            .outerjoin(
                subject_title, subject_title.id == func.coalesce(CuratedEntryItem.movie_title_id, Episode.title_id)
            )
            .where(
                CuratedEntry.category_id == category_id,
                CuratedEntry.removed_at.is_(None),
                Category.retired_at.is_(None),
            )
            .order_by(CuratedEntry.position, CuratedEntryItem.position_in_entry)
        )
    ).all()
    episode_ids = {row.episode_id for row in rows if row.episode_id is not None}
    order_rows = (
        (
            await session.execute(
                select(
                    EpisodeOrder.episode_id,
                    EpisodeOrder.order_type,
                    EpisodeOrder.label,
                    EpisodeOrder.sequence,
                    EpisodeOrder.order_season_number,
                    EpisodeOrder.order_episode_number,
                )
                .where(EpisodeOrder.episode_id.in_(episode_ids))
                .order_by(EpisodeOrder.order_type, EpisodeOrder.label, EpisodeOrder.sequence)
            )
        ).all()
        if episode_ids
        else []
    )
    orders: dict[uuid.UUID, list[tuple[str, str, int, int | None, int | None]]] = {}
    for order in order_rows:
        orders.setdefault(order.episode_id, []).append(
            (
                order.order_type,
                order.label,
                order.sequence,
                order.order_season_number,
                order.order_episode_number,
            )
        )
    entries: dict[uuid.UUID, dict[str, object]] = {}
    items: dict[uuid.UUID, list[dict[str, object]]] = {}
    numberings: dict[uuid.UUID, tuple[tuple[str, str], ...]] = {}
    occurrences: list[PlaybackOccurrence] = []
    for row in rows:
        if row.id not in entries:
            items[row.id] = []
            entries[row.id] = {
                **{column.key: row._mapping[column.key] for column in entry_columns},
                "title_media_type": row.title_media_type,
                "title_tmdb_id": row.title_tmdb_id,
                "items": items[row.id],
            }
            numberings[row.id] = numberings_for(
                CuratedEntry(
                    unit_kind=row.unit_kind,
                    order_type=row.order_type,
                    order_label=row.order_label,
                )
            )
        if row.position_in_entry is None:
            continue
        kind: Literal["episode", "title"] = "episode" if row.episode_id is not None else "title"
        identifier = row.episode_id if kind == "episode" else row.movie_title_id
        key = None
        if row.subject_tmdb_id is not None:
            key = tmdb_key(
                row.subject_media_type,
                row.subject_tmdb_id,
                season_number=row.episode_season,
                episode_number=row.episode_number,
            )
        occurrence = PlaybackOccurrence(
            entry_id=row.id,
            subject_kind=kind,
            subject_id_snapshot=identifier,
            tmdb_key=key,
            position_in_entry=row.position_in_entry,
        )
        applicable = [order for order in orders.get(row.episode_id, ()) if order[:2] in numberings[row.id]]
        items[row.id].append({**occurrence.model_dump(mode="json"), "numberings": applicable})
        if kind == subject_kind and identifier in subject_ids:
            occurrences.append(occurrence)
    canonical = json.dumps(
        {"category_id": category_id, "entries": list(entries.values())},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return PlaybackQueueSnapshot(fingerprint=hashlib.sha256(canonical).hexdigest(), occurrences=tuple(occurrences))
