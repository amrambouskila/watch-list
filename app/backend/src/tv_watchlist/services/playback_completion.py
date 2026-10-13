from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.models import CuratedEntry, PlaybackCompletion, PlaybackCompletionEvent
from tv_watchlist.models.playback_coverage import PlaybackCoverage
from tv_watchlist.models.playback_queue_snapshot import PlaybackQueueSnapshot


async def record_playback_completion(
    session: AsyncSession,
    entry: CuratedEntry,
    coverage: PlaybackCoverage,
    queue: PlaybackQueueSnapshot,
    selected_event_id: uuid.UUID,
    event_ids: list[uuid.UUID],
) -> None:
    """Append one receipt and its exact event membership inside the caller's transaction."""
    receipt = PlaybackCompletion(
        selected_watch_event_id=selected_event_id,
        category_id=entry.category_id,
        source_entry_id=entry.id,
        jellyfin_item_id_snapshot=coverage.jellyfin_item_id_snapshot,
        jellyfin_id_snapshot=coverage.jellyfin_id_snapshot,
        order_type=coverage.order_type,
        order_label=coverage.order_label,
        parent_index_number=coverage.parent_index_number,
        index_number=coverage.index_number,
        index_number_end=coverage.index_number_end,
        queue_fingerprint=queue.fingerprint,
        occurrence_snapshot=[occurrence.model_dump(mode="json") for occurrence in queue.occurrences],
    )
    session.add(receipt)
    await session.flush()
    session.add_all(
        PlaybackCompletionEvent(completion_id=receipt.id, watch_event_id=event_id) for event_id in event_ids
    )
    await session.flush()
