"""Universal constants describing the shape of the watch-order workbooks."""

from __future__ import annotations

from decimal import Decimal
from typing import Final

WATCH_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"watched"})
TITLE_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"title", "name", "show"})
ORDER_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"order", "#", "no", "num"})

# The headers the curated columns answer to, normalised the way `schema.normalize_header` normalises a
# header and then whitespace-collapsed. Read as aliases rather than by position, because nineteen
# workbooks head the same concept nine different ways ("Unit", "Season / Unit", "Season / Episode /
# Movie"), and because a workbook is free to carry none of them: WWII heads its third column "Event",
# which is the historical event rather than a unit, and Misc_Movies leaves every one of these blank.
UNIT_HEADER_ALIASES: Final[frozenset[str]] = frozenset(
    {"unit", "season unit", "season episode movie", "season episode block"}
)
RELEASE_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"release", "release date", "release date period"})
TYPE_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"type", "format"})

WATCH_HEADER_LABEL: Final[str] = "Watched?"
UNWATCHED: Final[str] = ""
WATCHED: Final[str] = "Watched"
IN_PROGRESS: Final[str] = "In progress"
SKIPPED: Final[str] = "Skip"
DEFAULT_WATCH_CHOICES: Final[tuple[str, ...]] = (UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED)

WATCHED_HIGHLIGHT_RGB: Final[str] = "FFDCFCE7"
DEFAULT_ACCENT_RGB: Final[str] = "FF1F2937"
TRANSPARENT_ARGB: Final[str] = "00000000"
HEADER_FONT_RGB: Final[str] = "FFFFFFFF"
WORKBOOK_FONT_NAME: Final[str] = "Carlito"
WORKBOOK_FONT_SIZE: Final[float] = 11.0
TABLE_STYLE_NAME: Final[str] = "TableStyleMedium2"

WATCH_COLUMN_WIDTH: Final[float] = 14.0
TITLE_COLUMN_WIDTH: Final[float] = 44.0
NOTES_COLUMN_WIDTH: Final[float] = 55.0
ORDER_COLUMN_WIDTH: Final[float] = 8.0
DEFAULT_COLUMN_WIDTH: Final[float] = 24.0
WIDE_HEADER_KEYWORDS: Final[tuple[str, ...]] = ("note", "when", "detail", "description")

HEADER_ROW: Final[int] = 1
FIRST_DATA_ROW: Final[int] = 2

EXCEL_LOCK_PREFIX: Final[str] = "~$"
WORKBOOK_SUFFIX: Final[str] = ".xlsx"
TEMP_WRITE_PREFIX: Final[str] = ".~tv-write-"
TEMP_WRITE_SUFFIX: Final[str] = ".tmp"
REPLACE_RETRIES: Final[int] = 5
REPLACE_RETRY_SECONDS: Final[float] = 0.08

DEFAULT_NEW_CATEGORY_COLUMNS: Final[tuple[str, ...]] = (
    "Order",
    "Title",
    "Unit",
    "Release",
    "Type",
    "When to Watch",
    "Notes",
    WATCH_HEADER_LABEL,
)
NEW_CATEGORY_SHEET_TITLE: Final[str] = "Master Watch Order"
NEW_CATEGORY_TABLE_SUFFIX: Final[str] = "MasterOrder"

BACKUP_DIRNAME: Final[str] = ".backups"
BACKUP_RETENTION: Final[int] = 10
BACKUP_INTERVAL_SECONDS: Final[float] = 900.0
BACKUP_TIMESTAMP_FORMAT: Final[str] = "%Y%m%d-%H%M%S"
# A retired category lands in the same folder as the snapshots and under the same stem, so its stamp
# wears this prefix and pruning leaves it alone however many snapshots a later namesake takes.
RETIRED_STAMP_PREFIX: Final[str] = "retired-"

MAX_TITLE_LENGTH: Final[int] = 120
MAX_CELL_LENGTH: Final[int] = 2000
MAX_NEW_CATEGORY_ROWS: Final[int] = 500
MAX_NEW_CATEGORY_COLUMNS: Final[int] = 64
MAX_FILENAME_STEM_LENGTH: Final[int] = 120
MAX_REASON_LENGTH: Final[int] = 240
MAX_PROPOSAL_CHANGES: Final[int] = 500
MAX_PROPOSAL_SOURCES: Final[int] = 20
MAX_CHAT_MESSAGE_LENGTH: Final[int] = 16000

# Characters Windows refuses in a filename, plus the device names it reserves at any extension.
ILLEGAL_FILENAME_CHARACTERS: Final[str] = r'<>:"/\|?*'
RESERVED_FILENAME_STEMS: Final[frozenset[str]] = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{digit}" for digit in range(1, 10)} | {f"lpt{digit}" for digit in range(1, 10)}
)

HERO_DIRNAME: Final[str] = "heroes"
HERO_ATTRIBUTION_FILENAME: Final[str] = "ATTRIBUTION.md"
MAX_HERO_CANDIDATES: Final[int] = 3
MAX_HERO_BYTES: Final[int] = 8_000_000
HERO_FETCH_TIMEOUT_SECONDS: Final[float] = 20.0
MAX_HERO_URL_LENGTH: Final[int] = 2000
MAX_HERO_SOURCE_FILE_LENGTH: Final[int] = 200
MAX_HERO_LICENCE_LENGTH: Final[int] = 80
MAX_HERO_DESCRIPTION_LENGTH: Final[int] = 240
HERO_SUFFIXES: Final[tuple[str, ...]] = (".png", ".svg", ".jpg", ".jpeg", ".webp", ".avif", ".gif")
HEX_COLOR_PATTERN: Final[str] = r"^#?[0-9A-Fa-f]{6}$"
HTTP_URL_PATTERN: Final[str] = r"^https?://"
# Control characters Excel refuses in a cell; openpyxl raises IllegalCharacterError on them.
ILLEGAL_CELL_CHARACTERS: Final[str] = "[\x00-\x08\x0b\x0c\x0e-\x1f]"

# Provider base URLs are constants, never configuration and never input (CLAUDE.md section 10.3, B10).
TMDB_API_BASE_URL: Final[str] = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL: Final[str] = "https://image.tmdb.org/t/p/"
TVDB_API_BASE_URL: Final[str] = "https://api4.thetvdb.com/v4"
PROVIDER_TIMEOUT_SECONDS: Final[float] = 20.0
MAX_PROVIDER_RESPONSE_BYTES: Final[int] = 8_000_000
# The one path segment that walks out of wherever it is joined to, spelled once for every reader of it:
# the outbound URL guard (`clients/http_guard.py`) and the torrent file name whose relative path is
# joined to a download directory (`models/qbittorrent/qbittorrent_file.py`).
TRAVERSAL_SEGMENT: Final[str] = ".."
# What an UNCONFIGURED client's pool is pinned to - shared by every upstream whose base is configuration
# rather than a constant (Jellyfin, qBittorrent). `configured` refuses every call before a URL is built,
# so nothing ever reaches this; it exists so that even a bug which got past that refusal is guarded
# against a base nothing listens on rather than against no base at all.
UNCONFIGURED_UPSTREAM_BASE_URL: Final[str] = "http://127.0.0.1:1"
# TMDB documents "somewhere in the 40 requests per second range" and says it could change; stay below it.
TMDB_REQUESTS_PER_SECOND: Final[float] = 30.0
# TheTVDB's limit is undocumented, so this is conservative by design (CLAUDE.md section 9.2).
TVDB_REQUESTS_PER_SECOND: Final[float] = 4.0
# TMDB's terms cap caching at six months, hard; refresh below it.
TMDB_CACHE_CEILING_DAYS: Final[int] = 170
# The TheTVDB bearer token lives one month and has no refresh endpoint, so it is replaced proactively.
TVDB_TOKEN_REFRESH_DAYS: Final[int] = 25
PROVIDER_BACKOFF_BASE_SECONDS: Final[float] = 60.0
PROVIDER_BACKOFF_MAX_SECONDS: Final[float] = 86_400.0

IDENTITY_HEADER_LABEL: Final[str] = "Row ID"
IDENTITY_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"row id", "rowid"})
# Wide enough for the canonical 36-character form, though the column itself is kept hidden.
IDENTITY_COLUMN_WIDTH: Final[float] = 38.0
# Bare `Final` on purpose: the value narrows to the `ColumnRole` member, so `_role_for` can return it.
IDENTITY_COLUMN_ROLE: Final = "identity"
POSITION_HEADER_LABEL: Final[str] = "Position (s)"
POSITION_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"position s"})
POSITION_COLUMN_WIDTH: Final[float] = 16.0
POSITION_COLUMN_ROLE: Final = "position"
# Player seconds use PostgreSQL INTEGER columns, not arbitrary-precision Python integers.
PLAYER_MAX_SECONDS: Final[int] = 2_147_483_647
# Roles the app mints and maintains itself, rather than ones the owner authored in Excel.
APP_OWNED_COLUMN_ROLES: Final[frozenset[str]] = frozenset({IDENTITY_COLUMN_ROLE, POSITION_COLUMN_ROLE})
# The headers those roles answer to. A create request may not author one, or the app would hide
# and later overwrite a column the owner meant to keep.
APP_OWNED_HEADER_ALIASES: Final[frozenset[str]] = IDENTITY_HEADER_ALIASES | POSITION_HEADER_ALIASES

# --- T19: the TMDB artwork byte cache (CLAUDE.md section 10.3, B11) ---------------------------------
# Provider artwork is cached on disk beside the Wikimedia marks, in its own subdirectory so a hand-made
# hero and a fetched poster can never collide on a name.
ARTWORK_SUBDIR: Final[str] = "tmdb"
# The one poster width the app caches bytes for. A TMDB image URL is COMPOSED as
# `secure_base_url + size + remote_path`; the size is ours, never a value a payload supplied.
TMDB_POSTER_SIZE: Final[str] = "w500"
# What a stored `artwork.remote_path` may look like before it is allowed into a URL: one leading
# slash, no second one, no dot-segment, no percent escape, and a raster extension. Anything else is
# refused before a request is built, so a crafted path cannot reach off the image host.
TMDB_REMOTE_PATH_PATTERN: Final[str] = r"^/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)$"
# One ingest pass may pull this many bytes of artwork in total before the cache stops fetching. The
# per-image cap is MAX_HERO_BYTES; this is the budget across a whole run.
MAX_ARTWORK_BYTES_PER_RUN: Final[int] = 200_000_000

# --- T15: the `sync_state` failure cursor -----------------------------------------------------------
# What `sync_state.last_error` may keep of a provider's message. The column is `Text`, so an upstream
# answering a megabyte of HTML would otherwise store all of it, on every retry, for every resource.
# Long enough for an exception class and its sentence; short enough that a cursor table stays a cursor
# table.
MAX_LAST_ERROR_CHARS: Final[int] = 500

# --- T23: the reconciler (Excel -> Postgres) --------------------------------------------------------
# How far a row may have moved and still be adopted by the entry it used to be, when its Row ID cell
# was cleared. Three rows either way covers a hand edit that inserted or removed a couple of entries
# above it; further than that the match is a guess, and a guess re-keys watch history onto the wrong
# row (master plan section 6.5, rule 3).
ADOPTION_POSITION_WINDOW: Final[int] = 3
# Past this share of unmatched rows, a workbook that HAS been ingested before is refused rather than
# re-keyed: a sort that excluded the last column, or a file replaced wholesale, looks exactly like this
# and re-minting would attach 141 rows to the wrong history (master plan section 6.3).
MISMATCH_REFUSAL_RATIO: Final[float] = 0.5

# --- T20: the specials bucket the aired walk creates -------------------------------------------------
# Season 0 is excluded from the aired rank, so it is given its own numbering rather than dropped. The
# label is what tells that ordering apart from a provider ordering of the same type, and it is the
# reason `episode_order.label` exists.
SPECIALS_ORDER_LABEL: Final[str] = "Specials"

# --- T25: the four-value `Watched?` mirror -----------------------------------------------------------
# How many times one mirror pass may attempt its write before leaving the identical diff to the next
# pass. The first attempt is guarded by the stamp the last ingest stored, so anything that saved the
# file since refuses it; each retry re-reads and re-checks that the rows it named still belong to the
# entries it planned against. Three is enough to ride out an unrelated save landing mid-pass and few
# enough that a workbook somebody is actively editing is left alone rather than fought over
# (master plan section 6.3 - the mirror is the writer that must lose).
MIRROR_RETRY_ATTEMPTS: Final[int] = 3
# What a `mirror_skipped_cell` / `excel_mirror` note keeps of the cell it echoes. `watch_event.note` is
# 240 characters, and a status column is free text until somebody types in it, so the echo is bounded
# well inside that and the template still fits beside it.
MAX_MIRROR_NOTE_LITERAL: Final[int] = 200
MIRROR_NOTE_TEMPLATE: Final[str] = "excel cell: {literal}"

# --- T28: the curated-entry projection endpoint ------------------------------------------------------
# One page of `GET /api/categories/{id}/entries`. The cap is both the default and the ceiling: the
# largest workbook holds 202 rows, so a single page still carries any category whole, and a request
# asking for more is refused at the boundary rather than served.
MAX_ENTRIES_PAGE_SIZE: Final[int] = 500

# --- T30: the resolution review queue ----------------------------------------------------------------
# What a human confirmation writes into `curated_entry.resolution_confidence`. A decimal, because the
# column is Numeric(3, 2) and a float there would round-trip through binary. 1.00 is the only value a
# heuristic can never produce, so "confirmed" is legible from the confidence alone as well as from the
# state (master plan section 6.5, rule 5).
CONFIRMED_RESOLUTION_CONFIDENCE: Final[Decimal] = Decimal("1.00")
# The clause a review decision leaves on `resolution_note`. Prefixed, like the expansion's `queue: `
# clause, so one pass can replace its own sentence without erasing the resolver's or the queue's.
REVIEW_NOTE_PREFIX: Final[str] = "review: "

# --- T27: the bootstrap run over the whole library ---------------------------------------------------
# The `job=` token every bootstrap log record carries, beside the reconciler's own `reconcile`. One
# word, so a whole run is `grep job=bootstrap` and a single workbook's pass is the record beside it.
BOOTSTRAP_JOB: Final[str] = "bootstrap"
# What the runnable hands the shell. Zero is "every workbook was reconciled or deliberately skipped";
# one is "at least one was refused", which is the only outcome the owner has to act on. Two is the
# third thing that can happen and is deliberately not folded into one: an unreachable database, a
# migration behind head, a credential the provider rejected - a fault in the run itself rather than a
# workbook declining to be written. A shell that cannot tell those apart retries the wrong one.
BOOTSTRAP_EXIT_OK: Final[int] = 0
BOOTSTRAP_EXIT_REFUSED: Final[int] = 1
BOOTSTRAP_EXIT_FAILED: Final[int] = 2

# --- T29: the watch-log request body ----------------------------------------------------------------
# What one watch event may carry about where it came from and why. Both are the widths of the columns
# behind them (`watch_event.device`, `watch_event.note`), named here so the request model, the column
# and the tests cannot drift apart. A device label is a short name a person typed; a note is the one
# free-text line an event carries, and the mirror's own echo of a status cell is bounded well inside it.
MAX_DEVICE_LENGTH: Final[int] = 120
MAX_NOTE_LENGTH: Final[int] = 240

# --- T48: the Jellyfin client (CLAUDE.md section 10.3, B16) -----------------------------------------
# Jellyfin's base URL is the ONE upstream address that is configuration rather than a constant - it is
# the owner's own LAN or loopback server, so it cannot be written down here. Everything else about the
# calls is fixed below, and the paths themselves are constants inside `clients/jellyfin_client.py`.
#
# The key rides in this header and in no other place: not a query parameter, not a log line, not the
# `<video src>` the browser holds. `GET /Videos/{id}/stream` would accept `?api_key=`, and a credential
# in a URL is a credential in every proxy log on the path, so this project never uses that form.
JELLYFIN_AUTH_HEADER: Final[str] = "Authorization"
JELLYFIN_AUTH_HEADER_TEMPLATE: Final[str] = 'MediaBrowser Token="{token}"'
# .NET ticks are 100 ns, so a whole second is ten million of them. This is the ONE divisor CLAUDE.md
# section 11.2 rule 7 names, applied once at the boundary; no ticks column exists anywhere downstream.
TICKS_PER_SECOND: Final[int] = 10_000_000
# The `ItemFields` values the sync stores, comma-delimited the way every Jellyfin array parameter is.
# Asking for less than the whole DTO is not an optimisation: `Path` and `ProviderIds` are omitted unless
# they are requested, and those two ARE the index. `DateLastSaved` is requested because the refresh
# cursor is written in terms of it - see the fixtures README for why it may not come back.
JELLYFIN_ITEM_FIELDS: Final[str] = "ProviderIds,Path,DateLastSaved"
# The three `BaseItemKind` values this project ever asks for. Plain strings rather than an enum: the
# ORM's own `JellyfinItemKind` belongs to `data/enums.py` at T49, and `clients/` may not import `data/`.
JELLYFIN_MOVIE_TYPE: Final[str] = "Movie"
JELLYFIN_SERIES_TYPE: Final[str] = "Series"
JELLYFIN_EPISODE_TYPE: Final[str] = "Episode"
# One page of `/Items`, and the hard stop on a walk. A server that reports more records than it hands
# back would otherwise loop for ever; 200 x 500 is a hundred thousand items, far past any personal
# library, so hitting the cap means the upstream is misbehaving rather than that the shelf is big.
JELLYFIN_PAGE_SIZE: Final[int] = 200
MAX_JELLYFIN_PAGES: Final[int] = 500
# Longer than the providers' 20 s: this is a LAN box that may be mid-scan, and the timeout applies per
# read rather than to a whole response, so a multi-gigabyte stream is unaffected by the number.
JELLYFIN_TIMEOUT_SECONDS: Final[float] = 30.0
# The one key a TMDB id is read out of `ProviderIds` by. The schema types that map as
# `additionalProperties: string` with NO enum, so `Tmdb`, `TMDB` and `tmdb` are all valid spellings and
# the live one is unconfirmed until T49 pages a real server (CLAUDE.md section 20.2, item 1). The
# lookup matches this constant case-insensitively, so the confirmed spelling changes exactly one line.
JELLYFIN_TMDB_PROVIDER_KEY: Final[str] = "Tmdb"
# What one item's strings may be before the boundary refuses them. `BaseItemDto` bounds none of these, so
# these are this project's caps rather than the schema's: an id is a 32-hex or dashed uuid, a name is a
# title, and a path is a filesystem path on the owner's own disk with room for deep anime season trees.
MAX_JELLYFIN_ID_LENGTH: Final[int] = 64
MAX_JELLYFIN_NAME_LENGTH: Final[int] = 500
MAX_JELLYFIN_PATH_LENGTH: Final[int] = 1000
# The ONLY upstream response headers the stream relay carries back. An allowlist, not a denylist: a
# Jellyfin `Set-Cookie` or `Server` must never reach the browser through the proxy (B17), and a header
# that is not named here cannot leak by being forgotten.
JELLYFIN_RELAYED_HEADERS: Final[tuple[str, ...]] = ("Content-Type", "Content-Length", "Content-Range")

# --- T60: the import pipeline (ADR-015) - the staging-folder scan and the qBittorrent client --------
# Video container formats this project ever treats as a media candidate. A sample, a subtitle track or
# an .nfo's neighbour never carries one of these, so the extension alone is not the whole filter -
# MEDIA_IMPORT_MIN_BYTES is the other half.
MEDIA_IMPORT_EXTENSIONS: Final[frozenset[str]] = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".webm"})
# Below this a file is a sample, a trailer, or an .nfo's neighbour, never the feature itself.
MEDIA_IMPORT_MIN_BYTES: Final[int] = 50_000_000
# Under this the row is `unidentified`, never a guess - the same coin-flip refusal the resolver already
# applies to a `Unit` cell it cannot parse unambiguously (master plan section 6.5, rule 5; Ruling 35).
MEDIA_IMPORT_MIN_CONFIDENCE: Final[float] = 0.80
MEDIA_IMPORT_TEMP_PREFIX: Final[str] = ".~tv-import-"
# Where a file the naming pass replaces is moved aside rather than overwritten - the artwork rule
# (`services/hero_backup.py`) applied to media: nothing this app can fetch again is ever deleted.
MEDIA_IMPORT_SUPERSEDED_DIRNAME: Final[str] = "_superseded"
MEDIA_IMPORT_TV_DIRNAME: Final[str] = "TV"
MEDIA_IMPORT_MOVIES_DIRNAME: Final[str] = "Movies"
# One page of `GET /api/imports`.
MAX_IMPORTS_PAGE_SIZE: Final[int] = 200

# qBittorrent WebUI API (https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)),
# read 2026-09-22. Every path below is a constant; the only caller-supplied value anywhere in the client
# is a torrent hash, validated against `^[0-9a-f]{40}$` before it ever reaches one of these
# (CLAUDE.md section 10.3, B21).
QBITTORRENT_TIMEOUT_SECONDS: Final[float] = 10.0
MAX_QBITTORRENT_RESPONSE_BYTES: Final[int] = 8_000_000
QBITTORRENT_LOGIN_PATH: Final[str] = "/api/v2/auth/login"
QBITTORRENT_TORRENTS_INFO_PATH: Final[str] = "/api/v2/torrents/info"
QBITTORRENT_TORRENTS_FILES_PATH: Final[str] = "/api/v2/torrents/files"
QBITTORRENT_WEBAPI_VERSION_PATH: Final[str] = "/api/v2/app/webapiVersion"

# --- T49: the Jellyfin library index (CLAUDE.md section 5.13) ----------------------------------------
# The two item types the paged `/Items` scan asks for. Episodes are deliberately NOT here: they come
# from `GET /Shows/{seriesId}/Episodes` per series, because the scan filters on `hasTmdbId=true` and an
# episode rarely carries its own TMDB id - asking for them in the same walk would index none of them.
JELLYFIN_INDEXED_ITEM_TYPES: Final[tuple[str, ...]] = (JELLYFIN_MOVIE_TYPE, JELLYFIN_SERIES_TYPE)
# The `job=` token every library-sync log record carries, beside `bootstrap` and `reconcile`.
LIBRARY_SYNC_JOB: Final[str] = "library_sync"
# The advisory-lock key `sync_library` takes for the length of its transaction, so two overlapping
# passes serialise instead of racing each other into a duplicate-key 500 on `uq_jellyfin_item_jellyfin_id`.
# An arbitrary but FIXED bigint: Postgres advisory locks share one namespace per database, so the value
# only has to be unique among this project's own locks, and it must never be derived from input.
LIBRARY_SYNC_ADVISORY_LOCK_KEY: Final[int] = 4_922_049_001

IMPORT_SCAN_JOB: Final[str] = "import_scan"
# Distinct from library sync; held through the caller's transaction so discovery cannot double-insert.
IMPORT_SCAN_ADVISORY_LOCK_KEY: Final[int] = 4_922_064_001
# Keep bound-parameter lists below asyncpg's limit even for a staging tree with many thousands of files.
MEDIA_IMPORT_LOOKUP_BATCH_SIZE: Final[int] = 1000

# --- T63: the import destination naming convention (ADR-015) ----------------------------------------
# A title is SANITISED for the filesystem here, never refused by it. `workbook/stem.validate_stem`
# rejects an illegal character, which is right for a workbook the owner typed a name for and wrong for
# a media path: `Blade II: Bloodhunt` and `Face/Off` are the real titles TMDB holds, and refusing them
# would leave a curated row unimportable. The two constants above (ILLEGAL_FILENAME_CHARACTERS,
# RESERVED_FILENAME_STEMS) are shared by both paths so the definitions can never drift apart.
#
# What an illegal character becomes. A space, not an empty string and not an underscore: deleting the
# character welds two words together (`Face/Off` -> `FaceOff`), and an underscore leaves
# punctuation-shaped scars across a whole library. The whitespace collapse that follows turns the run
# back into one space, so `Star Wars: Episode II` reads as a person would have typed it.
MEDIA_NAME_REPLACEMENT: Final[str] = " "
# Stripped from both ends of a component. Dots as well as spaces: Windows silently DROPS a trailing
# dot, so `Title.` is stored as `Title` and a path recorded with the dot would never find its own file
# again. Stripping the leading end is also what reduces a bare `..` to nothing, which is why no
# component this app emits can ever BE a traversal.
MEDIA_NAME_STRIP_CHARACTERS: Final[str] = " ."
# What a name Windows reserves gains, so `CON` becomes `CON_` and the title stays legible where
# replacing it outright would lose the work's name. Applied AFTER both length caps, never before:
# appending first and truncating second cuts the suffix straight back off, so `con` at a three-character
# limit would be filed as `con` again - a path Windows refuses - and `CONtact` capped to `CON` would
# have been manufactured into one. When there is no room to append, the tail is replaced (`con` ->
# `co_`) rather than the cap being exceeded.
MEDIA_RESERVED_STEM_SUFFIX: Final[str] = "_"
# Composed form, so `Pokemon` with an acute accent is one codepoint per glyph whichever form the
# provider sent and the path recorded matches the path on disk. Bare `Final` on purpose: the value
# narrows to the literal, and `unicodedata.normalize` takes one of four literals rather than any string.
MEDIA_NAME_NORMAL_FORM: Final = "NFC"
# What a component's length is measured in on disk, as opposed to in Python. Bare `Final` for the same
# reason as the normal form above: `bytes.decode` narrows better from a literal.
MEDIA_NAME_ENCODING: Final = "utf-8"
# The per-component byte cap every filesystem this app writes to enforces: ext4 and overlayfs under
# compose, APFS and NTFS on the owner's own machines, all 255 bytes for one path component. It is a
# SEPARATE limit from MAX_FILENAME_STEM_LENGTH and neither implies the other - a name is capped at 120
# CHARACTERS for legibility, and 113 characters of CJK is 339 BYTES, which is ENAMETOOLONG the moment
# T66 moves the file. `ワンピース` is three bytes a glyph, so anime is where this bites and Western titles
# never reach it.
MAX_MEDIA_COMPONENT_BYTES: Final[int] = 255
# Season and episode numbers are zero-padded to two digits and pass through UNPADDED above 99: Jellyfin
# reads `S01E1085` as readily as `S01E05`, and One Piece needs the four digits (section 11.2 rule 9).
MEDIA_NUMBER_PAD_WIDTH: Final[int] = 2
# The templates ADR-015 names, held here so the convention is one place rather than four f-strings.
# Season 0 takes the same template as any other season, so the specials bucket is `Season 00` with no
# special case. The episode marker is what Jellyfin's TMDB provider matches on, which is why it is
# never truncated: the series name is capped to leave room for it instead.
MEDIA_SEASON_DIRNAME_TEMPLATE: Final[str] = "Season {season:0{width}d}"
MEDIA_EPISODE_STEM_TEMPLATE: Final[str] = "{series} S{season:0{width}d}E{episode:0{width}d}"
MEDIA_EPISODE_TITLE_TEMPLATE: Final[str] = "{stem} - {episode_title}"
# A film's directory and its file carry the identical stem, which is the shape Jellyfin's movie scanner
# expects and what keeps a film's artwork beside it.
MEDIA_MOVIE_STEM_TEMPLATE: Final[str] = "{title} ({year})"

# --- T62: the read-only qBittorrent client (CLAUDE.md section 10.3, B21) ------------------------------
# Everything about the WebUI calls except the base URL, which is the owner's own configuration. The four
# PATH constants live in the T60 block above; the client splits each into segments so the shared URL
# builder percent-encodes them, and there is no second spelling of any path anywhere.
#
# The version floor is not a preference. The wiki dates two of the fields this client reads:
# `content_path` is "exposed since WebAPI v2.6.1" and a file's `index` is "since 2.8.2". A server below
# 2.8.2 simply does not send them, and guessing otherwise is the "do not guess field names" failure this
# client exists to avoid - so it is read once per session and refused by name.
QBITTORRENT_MIN_WEBAPI_VERSION: Final[str] = "2.8.2"
# The documented `filter` value for "finished downloading". The server's word for it; `progress` and
# `amount_left` are the file's own, and this client re-checks both.
QBITTORRENT_COMPLETED_FILTER: Final[str] = "completed"
# What `POST /api/v2/auth/login` answers on success. Anything else is a server that did not authenticate
# us, whatever status it chose to say it with.
QBITTORRENT_LOGIN_OK: Final[str] = "Ok."
# The two form fields the login body carries. The password is read into the second of these in exactly
# one place and reaches no URL, header, log record or exception message. The SID the response sets needs
# no constant: it is httpx's own cookie jar that stores and replays it, by the name the server chose.
QBITTORRENT_USERNAME_FIELD: Final[str] = "username"
QBITTORRENT_PASSWORD_FIELD: Final[str] = "password"  # noqa: S105 - a form FIELD NAME, never a password
# The two headers qBittorrent requires as CSRF protection: "Set Referer or Origin header to the exact same
# domain and port as used in the HTTP query Host header." Both are derived from the configured base and
# never from an inbound request header.
QBITTORRENT_REFERER_HEADER: Final[str] = "Referer"
QBITTORRENT_ORIGIN_HEADER: Final[str] = "Origin"
# The only caller-supplied value that ever reaches a qBittorrent URL, and it is checked against this
# before it does. Forty lowercase hex is a v1 (SHA-1) infohash and sixty-four is a v2 (SHA-256) one, and
# BOTH are recognised (R85): refusing v2 would have made one modern torrent fail a whole import pass
# rather than be skipped. Nothing else is - a length between them, an uppercase spelling, or anything
# carrying a separator is not an infohash this client will put in a URL.
QBITTORRENT_HASH_PATTERN: Final[str] = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
# What one row's strings may be before the boundary refuses them. The WebUI API bounds none of these, so
# these are this project's caps: a name is a release name, a path is a filesystem path on the owner's own
# disk, a state is one of a dozen documented words, and a version is `2.11.4`. The version cap matters
# most - it is the one upstream string this client repeats back, into a refusal message.
MAX_QBITTORRENT_HASH_LENGTH: Final[int] = 64
MAX_QBITTORRENT_NAME_LENGTH: Final[int] = 500
MAX_QBITTORRENT_PATH_LENGTH: Final[int] = 1000
MAX_QBITTORRENT_STATE_LENGTH: Final[int] = 32
MAX_QBITTORRENT_VERSION_LENGTH: Final[int] = 32

# --- Import filename identification ---------------------------------------------------------------
IMPORT_SEASON_EPISODE_CONFIDENCE: Final[float] = 0.95
IMPORT_ABSOLUTE_CONFIDENCE: Final[float] = 0.90
IMPORT_CROSS_EPISODE_CONFIDENCE: Final[float] = 0.90
IMPORT_PARENTHESISED_YEAR_CONFIDENCE: Final[float] = 0.95
IMPORT_RELEASE_YEAR_CONFIDENCE: Final[float] = 0.85
# SQL returns two leaders so an equal-scoring second title can never be silently discarded.
IMPORT_TITLE_CANDIDATE_LIMIT: Final[int] = 2

# Same-origin playback accepts one explicit-start ASCII byte range, never suffix or multipart ranges.
RANGE_HEADER_PATTERN: Final[str] = r"bytes=([0-9]+)-([0-9]*)"
DEFAULT_STREAM_CONTENT_TYPE: Final[str] = "video/mp4"

# Import move/recovery: platform ABI values, not filesystem-dependent policy.
IMPORT_RENAME_EXCL_DARWIN: Final[int] = 0x00000004
IMPORT_RENAME_NOREPLACE_LINUX: Final[int] = 1
IMPORT_AT_FDCWD_LINUX: Final[int] = -100
IMPORT_COPY_CHUNK_BYTES: Final[int] = 1024 * 1024
IMPORT_LOCK_KEY_BITS: Final[int] = 63
IMPORT_WIN_GENERIC_READ: Final[int] = 0x80000000
IMPORT_WIN_SHARE_READ_WRITE_DELETE: Final[int] = 0x00000007
IMPORT_WIN_OPEN_EXISTING: Final[int] = 3
IMPORT_WIN_OPEN_REPARSE_POINT: Final[int] = 0x00200000

# Episode-order coherence: two-int advisory keys are disjoint from the bigint import/library keys.
EPISODE_ORDER_LOCK_NAMESPACE: Final[int] = 0x45504F52
