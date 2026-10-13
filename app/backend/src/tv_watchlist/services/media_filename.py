"""One path component a filesystem can carry, out of a title a person wrote."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from tv_watchlist.constants import (
    ILLEGAL_FILENAME_CHARACTERS,
    MAX_FILENAME_STEM_LENGTH,
    MAX_MEDIA_COMPONENT_BYTES,
    MEDIA_NAME_ENCODING,
    MEDIA_NAME_NORMAL_FORM,
    MEDIA_NAME_REPLACEMENT,
    MEDIA_NAME_STRIP_CHARACTERS,
    MEDIA_RESERVED_STEM_SUFFIX,
    RESERVED_FILENAME_STEMS,
)
from tv_watchlist.data.errors import ImportNamingError

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
# Every character a filesystem refuses, plus every codepoint below a space - which is the definition of
# an ASCII control character, written as the boundary rather than as the number 32. One table rather
# than two passes, so the replacement is a single `str.translate` and cannot be half-applied.
_CONTROLS: Final[tuple[int, ...]] = tuple(range(ord(MEDIA_NAME_REPLACEMENT)))
_ILLEGAL: Final[tuple[int, ...]] = tuple(ord(character) for character in ILLEGAL_FILENAME_CHARACTERS)
_REPLACEMENTS: Final[dict[int, str]] = {codepoint: MEDIA_NAME_REPLACEMENT for codepoint in (*_CONTROLS, *_ILLEGAL)}


def component_bytes(value: str) -> int:
    """What this component costs against a filesystem's per-component byte cap."""
    return len(value.encode(MEDIA_NAME_ENCODING))


def _unreserved(component: str, limit: int) -> str:
    """`CON` made into a name Windows will carry, without growing past the limit that just capped it."""
    # Replacing the tail rather than appending when there is no room (`con` -> `co_` at a limit of three)
    # is the whole point of running this AFTER the cap: appending first and truncating second cuts the
    # suffix straight back off, and `con` would be filed as `con` again. Every reserved stem is ASCII, so
    # a character count is a byte count here and one comparison covers both limits.
    if len(component) + len(MEDIA_RESERVED_STEM_SUFFIX) > limit:
        component = component[: max(limit - len(MEDIA_RESERVED_STEM_SUFFIX), 0)]
    return f"{component}{MEDIA_RESERVED_STEM_SUFFIX}"


def _cleaned(value: str, limit: int, limit_bytes: int) -> str:
    """The sanitised component, possibly empty - the one place the order of the steps is written down."""
    component = unicodedata.normalize(MEDIA_NAME_NORMAL_FORM, value).translate(_REPLACEMENTS)
    component = _WHITESPACE.sub(MEDIA_NAME_REPLACEMENT, component).strip(MEDIA_NAME_STRIP_CHARACTERS)[:limit]
    encoded = component.encode(MEDIA_NAME_ENCODING)
    if len(encoded) > limit_bytes:
        # Decoded with `ignore`, which drops a trailing partial sequence rather than splitting a code
        # point: `ワ` is three bytes, so a cut in the middle of one would otherwise be an invalid name.
        component = encoded[:limit_bytes].decode(MEDIA_NAME_ENCODING, "ignore")
    # Stripped again after truncating, not only before: a cut at either limit can re-expose a trailing
    # dot or space, and Windows drops those silently, so the path recorded is not the path on disk.
    component = component.strip(MEDIA_NAME_STRIP_CHARACTERS)
    if component.lower() in RESERVED_FILENAME_STEMS:
        component = _unreserved(component, min(limit, limit_bytes))
    return component


def safe_component(
    value: str, *, limit: int = MAX_FILENAME_STEM_LENGTH, limit_bytes: int = MAX_MEDIA_COMPONENT_BYTES
) -> str:
    """One path component a filesystem can carry: Unicode kept, separators and control characters gone."""
    component = _cleaned(value, limit, limit_bytes)
    if not component:
        raise ImportNamingError(f"{value!r} carries nothing a filesystem can hold")
    return component


def optional_component(
    value: str | None, *, limit: int = MAX_FILENAME_STEM_LENGTH, limit_bytes: int = MAX_MEDIA_COMPONENT_BYTES
) -> str | None:
    """The component this value sanitises to, or None when it is absent, empty or nothing but punctuation.

    None is what lets a caller drop a whole segment AND its separator together, rather than leaving the
    dangling ` - ` an episode with no title would otherwise produce.
    """
    if value is None or limit < 1 or limit_bytes < 1:
        return None
    return _cleaned(value, limit, limit_bytes) or None
