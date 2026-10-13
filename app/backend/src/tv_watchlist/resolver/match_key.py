"""Title normalisation: the deterministic key `title.match_key` and `curated_entry.match_key` store."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# Folded away so the same work spelled three ways reaches one key. Quotes are deleted, because
# "Marvel's" must meet "Marvels"; dashes become a space, because "Spider-Man" must meet "Spider Man".
QUOTE_CHARACTERS: Final[str] = "'\"‘’‚‛“”„‟ʹʼ´`"
DASH_CHARACTERS: Final[str] = "-‐‑‒–—―⁃−－"
# The anime convention spells the letter as a multiplication sign - the library's own "Hunter x
# Hunter: G.I. Final" - where TMDB writes an ASCII x. Folded, not dropped, or the two spellings reach
# different keys. The fullwidth forms need no entry: NFKD and casefold already reduce them to "x".
CROSS_CHARACTERS: Final[str] = "×"
CROSS_REPLACEMENT: Final[str] = "x"

# Latin letters NFKD cannot take apart, because the stroke or the ligature is the letter rather than
# a combining mark on one. Without these the punctuation strip cuts the letter out and splits the
# word: the library's own "Kanał" keys as "kana". Applied after casefold, so an uppercase form and
# its lowercase twin reach the same output; the multi-letter expansions keep the word whole.
TRANSLITERATIONS: Final[dict[str, str]] = {
    "ł": "l",
    "Ł": "l",
    "ø": "o",
    "Ø": "o",
    "æ": "ae",
    "Æ": "ae",
    "œ": "oe",
    "Œ": "oe",
    "đ": "d",
    "Đ": "d",
    "þ": "th",
    "ð": "d",
}

# Dropped only when a word follows, so a category actually titled "The" keeps its one token.
LEADING_ARTICLES: Final[frozenset[str]] = frozenset({"the", "a", "an"})

# I-XX, the range a franchise instalment or an episode index ever reaches.
ROMAN_NUMERALS: Final[dict[str, int]] = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
    "xvi": 16,
    "xvii": 17,
    "xviii": 18,
    "xix": 19,
    "xx": 20,
}

# A roman numeral is read as a number only directly after one of these. Reading every whole token
# would turn the library's own "X-Men" into "10 men", "I Am Groot" into "1 am groot" and
# "V for Vendetta" into "5 for vendetta" - silently wrong matches, which the coverage probe named as
# the failure worth engineering against.
POSITIONAL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"episode", "ep", "part", "pt", "season", "series", "volume", "vol", "chapter", "book", "act", "movie", "film"}
)

_PARENTHETICAL: Final[re.Pattern[str]] = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_NON_ALPHANUMERIC: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9 ]+")
_FOLD_TABLE: Final[dict[int, str | None]] = {
    **{ord(character): None for character in QUOTE_CHARACTERS},
    **{ord(character): " " for character in DASH_CHARACTERS},
    **{ord(character): CROSS_REPLACEMENT for character in CROSS_CHARACTERS},
    **{ord(character): replacement for character, replacement in TRANSLITERATIONS.items()},
}

# A trailing "Part N" is an episode index rather than part of the title, so it is lifted off and
# handed back separately. "Parts 1-2" and a mid-title "Part 1:" are left exactly as they are.
_SUFFIX_SEPARATORS: Final[str] = DASH_CHARACTERS + ":,"
_SEPARATOR: Final[str] = rf"[\s{re.escape(_SUFFIX_SEPARATORS)}]"
_NOT_SEPARATOR: Final[str] = rf"[^\s{re.escape(_SUFFIX_SEPARATORS)}]"
# The lookbehind demands something that is not itself a separator before the run, so the title left
# behind can never come back empty: "Part 2" and "- Part 2" are whole titles, not suffixes on one.
_POSITIONAL_SUFFIX: Final[re.Pattern[str]] = re.compile(
    rf"(?<={_NOT_SEPARATOR}){_SEPARATOR}+\(?\[?\s*(?:part|pt\.?)\s+(\d{{1,3}})\s*\)?\]?\s*$", re.IGNORECASE
)

# A leading four-digit year, whatever the cell carries after it: "1999-2000", "1977-05-25", "2002".
# The cell itself stays verbatim in `curated_entry.raw_release`; this never coerces it into a date.
_LEADING_YEAR: Final[re.Pattern[str]] = re.compile(r"^\s*(\d{4})(?!\d)")


def normalise_title(title: str) -> str:
    """Fold to the comparable form: NFKD, casefold, parentheticals, folds, punctuation, numerals, article."""
    decomposed = _without_combining_marks(title)
    lowered = decomposed.casefold()
    unbracketed = _PARENTHETICAL.sub(" ", lowered)
    folded = unbracketed.translate(_FOLD_TABLE)
    plain = _NON_ALPHANUMERIC.sub(" ", folded)
    numbered = _with_numerals_normalised(plain.split())
    return " ".join(_without_a_leading_article(numbered))


def match_key(title: str, *, year: int | None = None) -> str:
    """The stored key: the normalised title, with the release year appended when one is known."""
    normalised = normalise_title(title)
    return normalised if year is None else f"{normalised} {year}".strip()


def strip_positional_suffix(title: str) -> tuple[str, int | None]:
    """A trailing "Part N" lifted off and returned beside the title; anything else is untouched."""
    stripped = title.strip()
    match = _POSITIONAL_SUFFIX.search(stripped)
    if match is None:
        return title, None
    return stripped[: match.start()], int(match.group(1))


def release_year(raw_release: str) -> int | None:
    """The leading four-digit year of a free-text `Release` cell, or None when it does not open with one."""
    match = _LEADING_YEAR.match(raw_release)
    return int(match.group(1)) if match else None


def _without_combining_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _with_numerals_normalised(tokens: list[str]) -> list[str]:
    return [
        str(ROMAN_NUMERALS[token]) if token in ROMAN_NUMERALS and _positional(tokens, index) else token
        for index, token in enumerate(tokens)
    ]


def _positional(tokens: list[str], index: int) -> bool:
    return index > 0 and tokens[index - 1] in POSITIONAL_KEYWORDS


def _without_a_leading_article(tokens: list[str]) -> list[str]:
    return tokens[1:] if len(tokens) > 1 and tokens[0] in LEADING_ARTICLES else tokens
