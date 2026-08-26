"""Normalisation applied to any string on its way into a worksheet cell."""

from __future__ import annotations

import re

from tv_watchlist.constants import ILLEGAL_CELL_CHARACTERS, MAX_CELL_LENGTH

_ILLEGAL = re.compile(ILLEGAL_CELL_CHARACTERS)


def sanitize(value: str, limit: int = MAX_CELL_LENGTH) -> str:
    """Strip control characters Excel rejects and clip to a length a cell can hold."""
    return _ILLEGAL.sub("", value)[:limit]
