"""How a page is ordered: title, year, media type, plausibility - and nothing about how popular a work is.

TMDB returns its results in popularity order, and taking the top one is how a 2025 remake wins a row about
the 1978 film. Every component below is a property of the row and the candidate together; none of them is a
property of the candidate alone, which is what a popularity rank is.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Final

from tv_watchlist.data.enums import UnitKind
from tv_watchlist.resolver.candidate import Candidate
from tv_watchlist.resolver.match_key import DASH_CHARACTERS, normalise_title
from tv_watchlist.resolver.resolution_request import ResolutionRequest


class TitleMatch(StrEnum):
    """How the row's title and the candidate's stand to each other, strongest first."""

    EXACT = "exact"
    # The row's title sits inside TMDB's: the sheet writes "Attack of the Clones" for "Star Wars:
    # Episode II - Attack of the Clones". Measured at ~17% of pairs, which is why it is a match at all.
    CONTAINED = "contained"
    # TMDB's whole title is the row title's leading segment, cut at a subtitle marker: TMDB's
    # "Pokémon: The First Movie" for the sheet's "Pokémon: The First Movie — Mewtwo Strikes Back".
    # Measured as the largest recoverable class of refusal in T31's dry run (Ruling 37). It is accepted
    # for FILMS with an agreeing year only; for a series the same shape is a season of a parent, which is
    # the second pass's job.
    EXTENDED = "extended"
    # TMDB's title is the front of the row's with no marker between them: "Superman" for "Superman
    # Returns". That is a different work, or the parent of the one the row means - a second-pass lead,
    # never a match.
    PARENT = "parent"
    WEAK = "weak"


class YearAgreement(StrEnum):
    AGREES = "agrees"
    UNKNOWN = "unknown"
    DISAGREES = "disagrees"


class TypeAgreement(StrEnum):
    AGREES = "agrees"
    UNKNOWN = "unknown"
    DISAGREES = "disagrees"


# A release cell and a catalogue date disagree by a day either side of New Year, and a film's sheet date is
# often its local release rather than TMDB's earliest, so one year of slack is the honest tolerance.
YEAR_TOLERANCE: Final[int] = 1
# One token is not evidence: "Superman" sits inside "Batman v Superman: Dawn of Justice". Two is.
MINIMUM_CONTAINED_TOKENS: Final[int] = 2
# Where a subtitle may begin. A colon, or any of the dash forms `match_key` already folds - surrounded by
# spaces, so a hyphenated word ("Spider-Man") is never cut in half.
SEGMENT_MARKERS: Final[re.Pattern[str]] = re.compile(rf":|\s[{re.escape(DASH_CHARACTERS)}]\s")
# Both a gate (`verification`) and a score component read this, so it lives with the score.
RUNTIME_TOLERANCE: Final[Decimal] = Decimal("0.25")

TITLE_SCORES: Final[dict[TitleMatch, Decimal]] = {
    TitleMatch.EXACT: Decimal("1.00"),
    TitleMatch.CONTAINED: Decimal("0.40"),
    # Below CONTAINED on purpose (Ruling 37): a hit the row merely extends must never outscore one whose
    # title the row actually carries.
    TitleMatch.EXTENDED: Decimal("0.25"),
    TitleMatch.PARENT: Decimal("0.10"),
    TitleMatch.WEAK: Decimal("0.00"),
}
YEAR_SCORES: Final[dict[YearAgreement, Decimal]] = {
    YearAgreement.AGREES: Decimal("0.50"),
    YearAgreement.UNKNOWN: Decimal("0.00"),
    YearAgreement.DISAGREES: Decimal("-0.50"),
}
# A disagreement is not a weak signal, it is a refusal, so it sinks a candidate below every other one
# rather than merely ranking it lower. The gate in `verification` rejects it too; this keeps the ordering
# honest for the note, which names the best hit even when nothing was accepted.
TYPE_SCORES: Final[dict[TypeAgreement, Decimal]] = {
    TypeAgreement.AGREES: Decimal("0.20"),
    TypeAgreement.UNKNOWN: Decimal("0.00"),
    TypeAgreement.DISAGREES: Decimal("-2.00"),
}
PLAUSIBLE_SCORE: Final[Decimal] = Decimal("0.10")
IMPLAUSIBLE_SCORE: Final[Decimal] = Decimal("-2.00")
UNKNOWN_SCORE: Final[Decimal] = Decimal("0.00")

_MATCH_RANK: Final[dict[TitleMatch, int]] = {
    TitleMatch.WEAK: 0,
    TitleMatch.PARENT: 1,
    TitleMatch.EXTENDED: 2,
    TitleMatch.CONTAINED: 3,
    TitleMatch.EXACT: 4,
}
# Both shapes say "TMDB's title is the front of this row's", which is what the second pass follows to find
# a parent series. Only their strength differs.
PARENT_LIKE_MATCHES: Final[frozenset[TitleMatch]] = frozenset({TitleMatch.EXTENDED, TitleMatch.PARENT})


def score_candidate(request: ResolutionRequest, candidate: Candidate) -> Decimal:
    """Pure. How well this candidate answers this row; higher is better, and popularity contributes zero."""
    return (
        TITLE_SCORES[title_match(request, candidate)]
        + YEAR_SCORES[year_agreement(request, candidate)]
        + TYPE_SCORES[type_agreement(request, candidate)]
        + _plausibility(runtime_is_plausible(request, candidate))
        + _plausibility(episode_count_is_plausible(request, candidate))
    )


def title_match(request: ResolutionRequest, candidate: Candidate) -> TitleMatch:
    """The strongest relation between the row's title and any name the candidate is known by."""
    query = request.query_key.split()
    if not query:
        return TitleMatch.WEAK
    segments = leading_segments(request.query_title)
    return max(
        (_match_against(query, normalise_title(name).split(), segments) for name in candidate.names),
        key=_MATCH_RANK.__getitem__,
    )


def leading_segments(title: str) -> frozenset[str]:
    """Every normalised leading part of `title` that a subtitle marker cuts off, the whole title excluded.

    "Pokémon: The First Movie — Mewtwo Strikes Back" yields "pokemon" and "pokemon the first movie": the
    second is the title TMDB carries, and the first is why every marker is tried rather than only the first.
    """
    return frozenset(
        segment for match in SEGMENT_MARKERS.finditer(title) if (segment := normalise_title(title[: match.start()]))
    )


def year_agreement(request: ResolutionRequest, candidate: Candidate) -> YearAgreement:
    """Whether the row's release year and the candidate's are within a year of each other."""
    if request.year is None or candidate.year is None:
        return YearAgreement.UNKNOWN
    return YearAgreement.AGREES if abs(request.year - candidate.year) <= YEAR_TOLERANCE else YearAgreement.DISAGREES


def type_agreement(request: ResolutionRequest, candidate: Candidate) -> TypeAgreement:
    """Whether the candidate is the kind of work the row states it is; a row that states none agrees with both."""
    expected = request.expected_media_type
    if expected is None:
        return TypeAgreement.UNKNOWN
    return TypeAgreement.AGREES if candidate.media_type == expected else TypeAgreement.DISAGREES


def runtime_is_plausible(request: ResolutionRequest, candidate: Candidate) -> bool | None:
    """Whether the candidate's runtime is within tolerance of the row's. `None` when either side is unknown."""
    expected = request.expected_runtime_minutes
    if expected is None or expected <= 0 or candidate.runtime_minutes is None:
        return None
    return abs(Decimal(candidate.runtime_minutes) - Decimal(expected)) / Decimal(expected) <= RUNTIME_TOLERANCE


def episode_count_is_plausible(request: ResolutionRequest, candidate: Candidate) -> bool | None:
    """Whether the row's episode span fits inside what TMDB lists. `None` when either side is unknown."""
    span = request.span.episode_span
    if span is None or candidate.episode_count is None or request.span.unit_kind is not UnitKind.EPISODES:
        return None
    return span[1] <= candidate.episode_count


def _plausibility(verdict: bool | None) -> Decimal:
    if verdict is None:
        return UNKNOWN_SCORE
    return PLAUSIBLE_SCORE if verdict else IMPLAUSIBLE_SCORE


def _match_against(query: list[str], name: list[str], segments: frozenset[str]) -> TitleMatch:
    if not name:
        return TitleMatch.WEAK
    if query == name:
        return TitleMatch.EXACT
    if len(query) >= MINIMUM_CONTAINED_TOKENS and _contains(name, query):
        return TitleMatch.CONTAINED
    if " ".join(name) in segments:
        return TitleMatch.EXTENDED
    return TitleMatch.PARENT if len(name) < len(query) and query[: len(name)] == name else TitleMatch.WEAK


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Whether `needle` appears in `haystack` as a contiguous run of whole tokens."""
    return any(haystack[start : start + len(needle)] == needle for start in range(len(haystack) - len(needle) + 1))
