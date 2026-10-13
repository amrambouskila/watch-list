"""Conservative single-episode and film release-filename parsing, with no I/O."""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Final

from tv_watchlist.constants import (
    IMPORT_ABSOLUTE_CONFIDENCE,
    IMPORT_CROSS_EPISODE_CONFIDENCE,
    IMPORT_PARENTHESISED_YEAR_CONFIDENCE,
    IMPORT_RELEASE_YEAR_CONFIDENCE,
    IMPORT_SEASON_EPISODE_CONFIDENCE,
    MEDIA_IMPORT_EXTENSIONS,
)
from tv_watchlist.models.filename_parse import FilenameParse
from tv_watchlist.resolver.match_key import normalise_title

_BRACKETS: Final = re.compile(r"\[[^\[\]]*\]")
_SEPARATORS: Final = re.compile(r"[._]+")
_SEASON_EPISODE: Final = re.compile(r"(?<!\w)s(?P<season>\d{1,3})e(?P<episode>\d{1,4})(?!\d)", re.I)
_CROSS_EPISODE: Final = re.compile(r"(?<!\w)(?P<season>\d{1,3})x(?P<episode>\d{1,4})(?!\d)", re.I)
_ABSOLUTE: Final = re.compile(r"\s+-\s*(?P<absolute>\d{1,5})(?:v\d+)?(?!\w)", re.I)
_MORE_EPISODES: Final = re.compile(r"^\s*(?:(?:[-+&]|to\b|and\b)\s*)?(?:[ex]\s*)?\d", re.I)
_YEAR: Final = re.compile(r"(?<!\w)(?P<year>(?:18|19|20|21)\d{2})(?!\w)")
_PARENTHESISED_YEAR: Final = re.compile(r"\((?P<year>(?:18|19|20|21)\d{2})\)")
_YEAR_RANGE: Final = re.compile(r"\b(?:18|19|20|21)\d{2}\s*(?:[-+&]|to\b)\s*(?:18|19|20|21)\d{2}\b", re.I)
_RELEASE_TOKENS: Final = re.compile(
    r"(?:^|\s)(?:\d{3,4}p|[xh][ .]?26[45]|hevc|av1|xvid|web[ -]?(?:dl|rip)|blu[ -]?ray|hdtv)\b.*$", re.I
)


def parse_filename(name: str) -> FilenameParse:
    """Return only an unambiguous single-item shape; an unsupported name carries no identity hints."""
    if any(character in name for character in ("/", "\\", "\x00")):
        return FilenameParse()
    suffix = PurePath(name).suffix
    stem = name[: -len(suffix)] if suffix.lower() in MEDIA_IMPORT_EXTENSIONS else name
    cleaned = _SEPARATORS.sub(" ", _BRACKETS.sub(" ", stem)).strip()
    if _YEAR_RANGE.search(cleaned) or len(_PARENTHESISED_YEAR.findall(cleaned)) > 1:
        return FilenameParse()
    if sum(len(pattern.findall(cleaned)) for pattern in (_SEASON_EPISODE, _CROSS_EPISODE, _ABSOLUTE)) > 1:
        return FilenameParse()
    for pattern, confidence in (
        (_SEASON_EPISODE, IMPORT_SEASON_EPISODE_CONFIDENCE),
        (_CROSS_EPISODE, IMPORT_CROSS_EPISODE_CONFIDENCE),
        (_ABSOLUTE, IMPORT_ABSOLUTE_CONFIDENCE),
    ):
        match = pattern.search(cleaned)
        if match is None:
            continue
        tail = _RELEASE_TOKENS.sub("", cleaned[match.end() :])
        if _MORE_EPISODES.match(tail):
            return FilenameParse()
        token, year = _title_and_year(cleaned[: match.start()])
        if not token:
            return FilenameParse()
        if pattern is _ABSOLUTE:
            number = int(match["absolute"])
            return (
                FilenameParse(series_token=token, year=year, absolute_number=number, confidence=confidence)
                if number
                else FilenameParse()
            )
        return FilenameParse(
            series_token=token,
            year=year,
            season_number=int(match["season"]),
            episode_number=int(match["episode"]),
            confidence=confidence,
        )
    for pattern, confidence in (
        (_PARENTHESISED_YEAR, IMPORT_PARENTHESISED_YEAR_CONFIDENCE),
        (_YEAR, IMPORT_RELEASE_YEAR_CONFIDENCE),
    ):
        matches = list(pattern.finditer(_RELEASE_TOKENS.sub("", cleaned)))
        if matches:
            match = matches[-1]
            token = _title_token(cleaned[: match.start()])
            return (
                FilenameParse(series_token=token, year=int(match["year"]), confidence=confidence)
                if token
                else FilenameParse()
            )
    return FilenameParse()


def _title_and_year(prefix: str) -> tuple[str, int | None]:
    cleaned = _RELEASE_TOKENS.sub("", prefix).strip()
    matches = list(_YEAR.finditer(cleaned))
    if matches:
        match = matches[-1]
        token = _title_token(cleaned[: match.start()])
        if token and not cleaned[match.end() :].strip(" ()"):
            return token, int(match["year"])
    return _title_token(cleaned), None


def _title_token(value: str) -> str:
    cleaned = " ".join(_RELEASE_TOKENS.sub("", value).split()).strip(" -()")
    return cleaned if normalise_title(cleaned) else ""
