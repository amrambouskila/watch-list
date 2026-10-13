"""The gate a top-scoring hit has to pass before it is written anywhere.

Scoring only orders a page; something always comes first, including on a page where nothing is right. A
confidently wrong match is the worst failure shape this project has (CLAUDE.md section 18.2, rule 2), so a
best hit that cannot be verified leaves the row unresolved with the reason recorded, and a human sees it.
"""

from __future__ import annotations

from typing import Final

from tv_watchlist.resolver.candidate import Candidate
from tv_watchlist.resolver.resolution_request import MOVIE, ResolutionRequest
from tv_watchlist.resolver.scoring import (
    RUNTIME_TOLERANCE,
    TitleMatch,
    TypeAgreement,
    YearAgreement,
    episode_count_is_plausible,
    runtime_is_plausible,
    title_match,
    type_agreement,
    year_agreement,
)

ACCEPTED_REASON: Final[str] = "accepted"
TYPE_REASON: Final[str] = "TMDB's media type is not the one this row states"
TITLE_REASON: Final[str] = "neither TMDB's title nor any alternative title it carries matches this row's"
YEAR_REASON: Final[str] = "the film's release year is not this row's"
CONTAINED_WITHOUT_A_YEAR_REASON: Final[str] = (
    "this row's title only sits inside TMDB's, and there is no release year to confirm which work it is"
)
EXTENDED_WITHOUT_A_YEAR_REASON: Final[str] = (
    "this row's title extends TMDB's, and there is no release year to confirm it is the same work"
)
EXTENDED_SERIES_REASON: Final[str] = (
    "this row's title extends TMDB's, and for a series that is a season of it rather than the series itself"
)
EPISODE_COUNT_REASON: Final[str] = "this row's episode span reaches past the last episode TMDB lists"
RUNTIME_REASON_TEMPLATE: Final[str] = "runtime {candidate} min is more than {tolerance:.0%} from this row's {expected}"


def runtime_reason(expected: int | None, candidate: int | None) -> str:
    """Why a runtime rejection happened, with both numbers, because the tolerance alone explains nothing."""
    return RUNTIME_REASON_TEMPLATE.format(candidate=candidate, tolerance=RUNTIME_TOLERANCE, expected=expected)


def verify(request: ResolutionRequest, candidate: Candidate) -> tuple[bool, str]:
    """Pure. `(accepted, reason)`; the reason is `ACCEPTED_REASON` only when every rule below passes."""
    if type_agreement(request, candidate) is TypeAgreement.DISAGREES:
        return False, TYPE_REASON
    match = title_match(request, candidate)
    if match in {TitleMatch.WEAK, TitleMatch.PARENT}:
        return False, TITLE_REASON
    # Ruling 37: a row whose title extends TMDB's is that film with a subtitle the catalogue leaves off -
    # but the same shape over a series is one of its seasons, which only the second pass may resolve.
    if match is TitleMatch.EXTENDED and candidate.media_type != MOVIE:
        return False, EXTENDED_SERIES_REASON
    year = year_agreement(request, candidate)
    # Only for a film. A series' `first_air_date` is when the SERIES began, and a curated TV row is dated by
    # the span it names: Inuyasha's sheet row reads 2009, and TMDB's InuYasha first aired in 2000. Rejecting
    # on that would refuse every season row in the library.
    if year is YearAgreement.DISAGREES and candidate.media_type == MOVIE:
        return False, YEAR_REASON
    if match is TitleMatch.CONTAINED and year is not YearAgreement.AGREES:
        return False, CONTAINED_WITHOUT_A_YEAR_REASON
    # The year is the whole of the evidence that the subtitle names the same work, so it must be present
    # and it must agree. A disagreement has already been refused above, for every film.
    if match is TitleMatch.EXTENDED and year is not YearAgreement.AGREES:
        return False, EXTENDED_WITHOUT_A_YEAR_REASON
    if runtime_is_plausible(request, candidate) is False:
        return False, runtime_reason(request.expected_runtime_minutes, candidate.runtime_minutes)
    if episode_count_is_plausible(request, candidate) is False:
        return False, EPISODE_COUNT_REASON
    return True, ACCEPTED_REASON
