"""Translation between workbook filenames and category ids."""

from __future__ import annotations

import re
from pathlib import Path

from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.workbook.errors import InvalidNameError
from tv_watchlist.workbook.stem import validate_stem

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_UNFILABLE = re.compile(r"[^A-Za-z0-9 _-]+")
_WHITESPACE = re.compile(r"\s+")


def slugify(value: str) -> str:
    """Lowercase, hyphen-joined identifier safe for use in a URL path segment."""
    return _NON_ALNUM.sub("-", value.lower()).strip("-")


def category_id(path: Path) -> str:
    """Stable id for a workbook, derived from its filename."""
    return slugify(path.stem)


def workbook_filename(name: str) -> str:
    """Filename for a new category: the name verbatim, with unfilable runs as one underscore."""
    stem = validate_stem(_WHITESPACE.sub("_", _UNFILABLE.sub(" ", name).strip()))
    # The whole app addresses a category by the id its filename slugifies to, so an empty one is unusable.
    if not slugify(stem):
        raise InvalidNameError("a name needs at least one letter or number")
    return f"{stem}{WORKBOOK_SUFFIX}"
