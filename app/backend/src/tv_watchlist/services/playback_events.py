from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.constants import PLAYER_MAX_SECONDS
from tv_watchlist.data.enums import (
    JellyfinItemKind,
    ResolutionState,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
)
from tv_watchlist.data.episode_order_lock import try_episode_order_locks
from tv_watchlist.data.errors import PlaybackStateError
from tv_watchlist.data.models import CuratedEntry, CuratedEntryItem, EpisodeOrder, JellyfinItem
from tv_watchlist.models.playback_coverage import PlaybackCoverage
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.models.watch_event_read import WatchEventRead
from tv_watchlist.services.episode_match import EpisodeMatch, MatchState, episodes_for_entry
from tv_watchlist.services.library_selections import library_selections_for
from tv_watchlist.services.locked_curated_entry import locked_curated_entry
from tv_watchlist.services.playback_completion import record_playback_completion
from tv_watchlist.services.playback_queue_snapshot import capture_playback_queue
from tv_watchlist.services.watch_events import record_watch_event


async def record_playback_event(
    session: AsyncSession, body: WatchEventCreate, entry_id: uuid.UUID, file_id: uuid.UUID
) -> WatchEventRead:
    """Validate a cached file selection and append one atomic player snapshot, including range siblings."""
    entry, category = await locked_curated_entry(session, entry_id)
    if body.category_id is not None and body.category_id != category.id:
        raise PlaybackStateError("The playback snapshot names a different workbook.")
    if body.kind not in (WatchEventKind.PROGRESSED, WatchEventKind.COMPLETED) or body.position_seconds is None:
        raise PlaybackStateError("Player snapshots require progress or completion with an integer position.")
    if body.position_seconds > PLAYER_MAX_SECONDS or (
        body.runtime_seconds is not None and body.runtime_seconds > PLAYER_MAX_SECONDS
    ):
        raise PlaybackStateError("Player position and runtime exceed the supported storage range.")
    if body.kind is WatchEventKind.COMPLETED and (
        body.runtime_seconds is None or body.position_seconds < body.runtime_seconds
    ):
        raise PlaybackStateError("Completion requires the end of a file with a known positive runtime.")
    if entry.resolution_state not in (ResolutionState.AUTO, ResolutionState.CONFIRMED):
        raise PlaybackStateError("The selected entry no longer has a resolved playback subject.")
    if body.kind is WatchEventKind.COMPLETED:
        title_ids = set(
            await session.scalars(
                select(CuratedEntry.title_id).where(
                    CuratedEntry.category_id == category.id,
                    CuratedEntry.removed_at.is_(None),
                    CuratedEntry.title_id.is_not(None),
                )
            )
        )
        if not await try_episode_order_locks(session, title_ids, shared=True):
            raise PlaybackStateError("Episode numbering is changing; retry the playback snapshot.")
    coverage = await _coverage(session, entry, body, file_id)
    queue = (
        await capture_playback_queue(session, category.id, coverage.subject_kind, coverage.subject_ids)
        if body.kind is WatchEventKind.COMPLETED
        else None
    )
    snapshot = body.model_copy(
        update={
            "category_id": category.id,
            "occurred_at": body.occurred_at or utcnow(),
            "position_seconds": min(body.position_seconds, body.runtime_seconds)
            if body.runtime_seconds is not None
            else body.position_seconds,
        }
    )
    # The selected event is last so its response includes every sibling's derived completion.
    event_ids: list[uuid.UUID] = []
    for subject_id in sorted(coverage.subject_ids - {body.subject_id}):
        sibling = await record_watch_event(
            session,
            snapshot.model_copy(update={"subject_id": subject_id}),
            source=WatchEventSource.PLAYER,
            playback_entry=entry,
        )
        event_ids.append(sibling.id)
    selected = await record_watch_event(session, snapshot, source=WatchEventSource.PLAYER, playback_entry=entry)
    event_ids.append(selected.id)
    if queue is not None:
        await record_playback_completion(session, entry, coverage, queue, selected.id, event_ids)
    return selected


async def _coverage(
    session: AsyncSession, entry: CuratedEntry, body: WatchEventCreate, file_id: uuid.UUID
) -> PlaybackCoverage:
    # A sync can replace numbering without taking the category lock; retain the exact file evidence.
    file = await session.scalar(
        select(JellyfinItem)
        .where(JellyfinItem.id == file_id, JellyfinItem.removed_at.is_(None))
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if file is None:
        raise PlaybackStateError("The selected playback file is no longer available.")
    if body.subject_kind is WatchSubjectKind.EPISODE:
        matches = await episodes_for_entry(session, entry)
        match = next((match for match in matches if match.episode_id == body.subject_id), None)
        if match is None or match.state is not MatchState.MATCHED or match.jellyfin_item_id != file_id:
            raise PlaybackStateError("The episode no longer matches the selected playback file.")
        subjects = (
            await _covered_episodes(session, entry, match, file)
            if body.kind is WatchEventKind.COMPLETED and match.covers_range
            else {body.subject_id}
        )
        return PlaybackCoverage(
            subject_kind="episode",
            subject_ids=frozenset(subjects),
            jellyfin_item_id_snapshot=file.id,
            jellyfin_id_snapshot=file.jellyfin_id,
            order_type=match.order_type,
            order_label=match.order_label,
            parent_index_number=file.parent_index_number,
            index_number=file.index_number,
            index_number_end=file.index_number_end,
        )
    if body.subject_kind is WatchSubjectKind.TITLE:
        slot = await session.scalar(
            select(CuratedEntryItem.id).where(
                CuratedEntryItem.curated_entry_id == entry.id, CuratedEntryItem.movie_title_id == body.subject_id
            )
        )
        selections = await library_selections_for(session, {body.subject_id})
        selection = selections.get(body.subject_id)
        if (
            slot is None
            or selection is None
            or selection.ambiguous
            or selection.item_id != file_id
            or file.kind is not JellyfinItemKind.MOVIE
        ):
            raise PlaybackStateError("The movie no longer matches the selected playback file.")
        return PlaybackCoverage(
            subject_kind="title",
            subject_ids=frozenset({body.subject_id}),
            jellyfin_item_id_snapshot=file.id,
            jellyfin_id_snapshot=file.jellyfin_id,
        )
    raise PlaybackStateError("Player snapshots must name the selected episode or movie.")


async def _covered_episodes(
    session: AsyncSession, entry: CuratedEntry, match: EpisodeMatch, file: JellyfinItem
) -> set[uuid.UUID]:
    if file.index_number is None or file.index_number_end is None:
        raise PlaybackStateError("The completed file no longer has a complete episode range.")
    numbered = list(
        await session.execute(
            select(EpisodeOrder.episode_id, EpisodeOrder.order_episode_number).where(
                EpisodeOrder.title_id == entry.title_id,
                EpisodeOrder.order_type == match.order_type,
                EpisodeOrder.label == match.order_label,
                EpisodeOrder.order_season_number == file.parent_index_number,
                EpisodeOrder.order_episode_number.between(file.index_number, file.index_number_end),
            )
        )
    )
    episodes = {row.episode_id for row in numbered}
    numbers = {row.order_episode_number for row in numbered}
    expected = file.index_number_end - file.index_number + 1
    if len(numbered) != expected or len(numbers) != expected or match.episode_id not in episodes:
        raise PlaybackStateError("The file's complete episode range is missing or ambiguous in the stored numbering.")
    return episodes
