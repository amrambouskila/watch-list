"""The closed vocabularies the schema shares - the one sanctioned multi-concept module (CLAUDE.md section 3.1)."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM


class MediaType(StrEnum):
    MOVIE = "movie"
    TV = "tv"


class OrderType(StrEnum):
    """The numberings the app itself computes with."""

    # Not a database vocabulary: `episode_order.order_type` is a plain string, because TheTVDB's season
    # types are read at runtime from `GET /v4/seasons/types` and a type this enum has never seen must
    # still be storable (master plan section 10.1).
    AIRED = "aired"
    ABSOLUTE = "absolute"
    DVD = "dvd"
    ALTERNATE = "alternate"


class UnitKind(StrEnum):
    MOVIE = "movie"
    EPISODES = "episodes"
    SEASON = "season"
    SERIES = "series"
    SPECIAL = "special"
    UNKNOWN = "unknown"


class ResolutionState(StrEnum):
    UNRESOLVED = "unresolved"
    AUTO = "auto"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class EntityKind(StrEnum):
    TITLE = "title"
    SEASON = "season"
    EPISODE = "episode"


class ExternalSource(StrEnum):
    """The providers Phase 1 keys against. A later phase's label needs its own enum-altering revision."""

    TMDB = "tmdb"
    TVDB = "tvdb"
    IMDB = "imdb"
    WIKIDATA = "wikidata"


class ArtworkKind(StrEnum):
    POSTER = "poster"
    BACKDROP = "backdrop"
    LOGO = "logo"
    STILL = "still"


class WatchEventKind(StrEnum):
    STARTED = "started"
    PROGRESSED = "progressed"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    UNSET = "unset"


class WatchEventSource(StrEnum):
    UI = "ui"
    EXCEL_MIRROR = "excel_mirror"
    # Playback events come from the browser's own <video> element, so the source is the player, not the
    # server that streamed the file.
    PLAYER = "player"


class WatchSubjectKind(StrEnum):
    EPISODE = "episode"
    TITLE = "title"
    CURATED_ENTRY = "curated_entry"


class SyncResourceType(StrEnum):
    """The resources Phase 1 caches in `sync_state`. A later phase's label needs its own revision."""

    TMDB_CONFIGURATION = "tmdb_configuration"
    TMDB_MOVIE = "tmdb_movie"
    TMDB_TV = "tmdb_tv"
    TMDB_SEASON = "tmdb_season"
    TMDB_EXTERNAL_IDS = "tmdb_external_ids"
    TMDB_ALTERNATIVE_TITLES = "tmdb_alternative_titles"
    TMDB_CHANGES = "tmdb_changes"
    TVDB_SEASON_TYPES = "tvdb_season_types"
    TVDB_EPISODES = "tvdb_episodes"
    TVDB_UPDATES = "tvdb_updates"


class JellyfinItemKind(StrEnum):
    """The three `BaseItemDto.Type` values the library index stores, lowercased into this schema's idiom.

    Jellyfin's own vocabulary is far wider (`Folder`, `BoxSet`, `Audio`, …); these are the three that are
    playable units in a curated order, and an item of any other type is skipped by the sync rather than
    stored under a label this enum would have to grow for (T49).
    """

    MOVIE = "movie"
    SERIES = "series"
    EPISODE = "episode"


class Availability(StrEnum):
    """Computed library state; deliberately not a native Postgres enum."""

    IN_LIBRARY = "in_library"
    NOT_IN_LIBRARY = "not_in_library"
    AMBIGUOUS = "ambiguous"


class MediaImportSource(StrEnum):
    """Where the import scan found a file - Phase 3.5's provenance table (ADR-015, T61)."""

    STAGING_FOLDER = "staging_folder"
    QBITTORRENT_COMPLETED = "qbittorrent_completed"
    MANUAL = "manual"


class MediaImportIdentifiedBy(StrEnum):
    """How a file was matched to a title - a filename parse, or the owner's own pick."""

    FILENAME = "filename"
    OWNER_PICK = "owner_pick"


class MediaImportStatus(StrEnum):
    """One file's progress through the pipeline: found, matched, moved, hashed, indexed - or stopped."""

    FOUND = "found"
    IDENTIFIED = "identified"
    MOVED = "moved"
    HASHED = "hashed"
    REFRESHED = "refreshed"
    FAILED = "failed"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    UNIDENTIFIED = "unidentified"


class MediaImportOperationPhase(StrEnum):
    """Durable import intent, filesystem progress, commit and compensation."""

    PREPARED = "prepared"
    COPIED = "copied"
    INSTALLED = "installed"
    COMMITTED = "committed"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    FAILED = "failed"


def pg_enum(members: type[StrEnum], name: str) -> ENUM:
    """A native Postgres enum whose labels are the member VALUES (`aired`), never the names (`AIRED`)."""
    # create_type=False: the first migration creates every type once, explicitly, because several tables
    # share one type and per-table auto-creation would collide.
    return ENUM(
        members,
        name=name,
        values_callable=lambda enum: [member.value for member in enum],
        create_type=False,
    )
