"""Reduce fetched markup to the readable text the model is meant to reason over."""

from __future__ import annotations

import re
from html import unescape

_DROPPED_ELEMENTS = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")


def html_to_text(markup: str) -> str:
    """Markup with script/style bodies removed, tags reduced to separators and entities decoded."""
    without_code = _DROPPED_ELEMENTS.sub(" ", markup)
    return _WHITESPACE.sub(" ", unescape(_TAG.sub(" ", without_code))).strip()
