"""Every ORM model, imported here so `Base.metadata` is complete wherever this package is imported (Alembic, tests)."""

from __future__ import annotations

from typing import Final

from tv_watchlist.data.base import Base
from tv_watchlist.data.models.artwork import Artwork
from tv_watchlist.data.models.category import Category
from tv_watchlist.data.models.curated_entry import CuratedEntry
from tv_watchlist.data.models.curated_entry_item import CuratedEntryItem
from tv_watchlist.data.models.episode import Episode
from tv_watchlist.data.models.episode_order import EpisodeOrder
from tv_watchlist.data.models.external_id import ExternalId
from tv_watchlist.data.models.jellyfin_item import JellyfinItem
from tv_watchlist.data.models.media_import import MediaImport
from tv_watchlist.data.models.media_import_operation import MediaImportOperation
from tv_watchlist.data.models.playback_completion import PlaybackCompletion
from tv_watchlist.data.models.playback_completion_event import PlaybackCompletionEvent
from tv_watchlist.data.models.season import Season
from tv_watchlist.data.models.sync_state import SyncState
from tv_watchlist.data.models.title import Title
from tv_watchlist.data.models.watch_event import WatchEvent

ALL_MODELS: Final[tuple[type[Base], ...]] = (
    Artwork,
    Category,
    CuratedEntry,
    CuratedEntryItem,
    Episode,
    EpisodeOrder,
    ExternalId,
    JellyfinItem,
    MediaImport,
    MediaImportOperation,
    PlaybackCompletion,
    PlaybackCompletionEvent,
    Season,
    SyncState,
    Title,
    WatchEvent,
)

__all__ = [
    "ALL_MODELS",
    "Artwork",
    "Category",
    "CuratedEntry",
    "CuratedEntryItem",
    "Episode",
    "EpisodeOrder",
    "ExternalId",
    "JellyfinItem",
    "MediaImport",
    "MediaImportOperation",
    "PlaybackCompletion",
    "PlaybackCompletionEvent",
    "Season",
    "SyncState",
    "Title",
    "WatchEvent",
]
