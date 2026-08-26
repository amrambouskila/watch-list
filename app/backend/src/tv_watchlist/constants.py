"""Universal constants describing the shape of the watch-order workbooks."""

from __future__ import annotations

from typing import Final

WATCH_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"watched"})
TITLE_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"title", "name", "show"})
ORDER_HEADER_ALIASES: Final[frozenset[str]] = frozenset({"order", "#", "no", "num"})

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
