"""Check a filename stem the way the filesystem would, for the two places one is chosen."""

from __future__ import annotations

from tv_watchlist.constants import (
    ILLEGAL_FILENAME_CHARACTERS,
    MAX_FILENAME_STEM_LENGTH,
    RESERVED_FILENAME_STEMS,
    WORKBOOK_SUFFIX,
)
from tv_watchlist.workbook.errors import InvalidNameError


def validate_stem(stem: str) -> str:
    """Check a filename stem the way the filesystem would, with a message worth reading."""
    cleaned = stem.strip().rstrip(". ")
    if not cleaned:
        raise InvalidNameError("a name is required")
    if len(cleaned) > MAX_FILENAME_STEM_LENGTH:
        raise InvalidNameError(f"keep it under {MAX_FILENAME_STEM_LENGTH} characters")
    if cleaned.lower().endswith(WORKBOOK_SUFFIX):
        cleaned = cleaned[: -len(WORKBOOK_SUFFIX)].rstrip(". ")
    illegal = sorted({character for character in cleaned if character in ILLEGAL_FILENAME_CHARACTERS})
    if illegal:
        raise InvalidNameError(f"a filename cannot contain {' '.join(illegal)}")
    if any(ord(character) < 32 for character in cleaned):
        raise InvalidNameError("a filename cannot contain control characters")
    if cleaned.lower() in RESERVED_FILENAME_STEMS:
        raise InvalidNameError(f"{cleaned} is a name Windows reserves")
    return cleaned
