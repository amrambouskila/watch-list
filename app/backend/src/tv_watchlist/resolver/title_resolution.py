"""What one curated row resolves to at TMDB, how far that can be trusted, and why.

Two passes, stopping at the first that produces a verified candidate: the franchise-expanded top-level
search, and - inside a matched parent series - its season and season-zero episode names. Nothing here ever
returns `confirmed`: a human does that in T30.

A third pass was designed and dropped: asking `alternative_titles` what else the best unmatched hit is
called. Choosing WHICH hit to ask needs a ranking, and among hits that match the row's title in no way at
all the only ranking available is TMDB's own relevance order - which is the one thing this module may not
rank by. Alternative titles still take part for free, through each hit's `original_title`/`original_name`
(see `Candidate.from_search_hit`); a row written under a name TMDB carries only regionally lands in the
review queue instead, which is what that queue is for.

The T16 ruling that a trailing roman numeral should also be searched in its arabic form is RETIRED
(Ruling 34): measured over all 996 rows it rescues none, TMDB spells `Blade II` exactly as the sheet
does, and each extra form costs a live search.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from tv_watchlist.clients.errors import ProviderError
from tv_watchlist.clients.tmdb_client import TmdbClient
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType
from tv_watchlist.models.tmdb.tmdb_search_page import TmdbSearchPage
from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
from tv_watchlist.models.tmdb.tmdb_tv import TmdbTv
from tv_watchlist.resolver.candidate import Candidate, MatchedUnit
from tv_watchlist.resolver.franchise import FRANCHISE_WORD_SEPARATOR, franchise_candidates
from tv_watchlist.resolver.match_key import normalise_title, release_year
from tv_watchlist.resolver.resolution_request import MOVIE, TV, ResolutionRequest
from tv_watchlist.resolver.scoring import (
    PARENT_LIKE_MATCHES,
    TitleMatch,
    YearAgreement,
    score_candidate,
    title_match,
    year_agreement,
)
from tv_watchlist.resolver.verification import verify

# The rungs. Each one states what was actually established, and none of them is `confirmed`: `auto` is not
# trusted (master plan R1), and the review queue is what turns one of these into a human's answer.
EXACT_WITH_YEAR_CONFIDENCE: Final[Decimal] = Decimal("0.95")
EXACT_WITHOUT_YEAR_CONFIDENCE: Final[Decimal] = Decimal("0.80")
# One rung for every match where the title the sheet wrote is not the title TMDB carries: through a
# franchise template, or by sitting inside TMDB's title. Both say the same thing about how much was
# established, so they are worth the same.
WEAKER_TITLE_CONFIDENCE: Final[Decimal] = Decimal("0.65")
SECOND_PASS_CONFIDENCE: Final[Decimal] = Decimal("0.50")
UNRESOLVED_CONFIDENCE: Final[Decimal] = Decimal("0.00")

SPECIALS_SEASON: Final[int] = 0
# A one-token remainder ("Special") would prefix-match half a specials bucket, so a prefix match needs two.
SECOND_PASS_MINIMUM_TOKENS: Final[int] = 2
MAX_ALTERNATIVES: Final[int] = 5
# A note carries provider text and is logged, so it is bounded and stripped like any untrusted echo
# (CLAUDE.md section 10.3, B12/B14).
MAX_NOTE_LITERAL: Final[int] = 120
_CONTROL_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\r\n]")
TITLE_SEGMENT_SEPARATOR: Final[str] = ":"

EXACT_WITH_YEAR_NOTE: Final[str] = "TMDB's title and release year both match this row"
EXACT_WITHOUT_YEAR_NOTE: Final[str] = "TMDB's title matches this row; no release year to confirm it against"
UNUSED_YEAR_NOTE: Final[str] = (
    "TMDB's title matches this row; this row's release year is its span's, so a series' first air date "
    "is not compared against it"
)
CONTAINED_NOTE_TEMPLATE: Final[str] = "this row's title sits inside TMDB's \"{name}\", and the years agree"
EXTENDED_NOTE_TEMPLATE: Final[str] = "this row's title extends TMDB's \"{name}\"; the years agree"
THROUGH_QUERY_TEMPLATE: Final[str] = 'found by searching the franchise form "{query}"'
SEASON_NOTE_TEMPLATE: Final[str] = 'matched season {season} "{name}" inside TMDB tv {parent}'
EPISODE_NOTE_TEMPLATE: Final[str] = 'matched season {season} episode {episode} "{name}" inside TMDB tv {parent}'
AMBIGUOUS_NOTE_TEMPLATE: Final[str] = (
    "{count} candidates score exactly the same, so this row is left for a human: {listed}"
)
AND_MORE_TEMPLATE: Final[str] = ", and {count} more"
NOTHING_MATCHED_NOTE: Final[str] = "TMDB answered with nothing that matches this row"
REJECTED_NOTE_TEMPLATE: Final[str] = "best TMDB hit {description} was refused: {reason}"
PROVIDER_NOTE_TEMPLATE: Final[str] = "TMDB could not answer ({error})"
DESCRIPTION_TEMPLATE: Final[str] = '{media_type} {tmdb_id} "{name}" ({year})'
CHOSEN_NOTE_TEMPLATE: Final[str] = "{why} - TMDB {description}"


@dataclass(frozen=True, slots=True)
class TitleResolution:
    """One row's answer: `auto` with a candidate and a reason, or `unresolved` with the reason it is not.

    `unit_kind` is the kind T19 stores. It is the span's own kind, except that a blank `Unit` cell takes the
    matched media type's kind instead - Ruling 27, which 66 Misc_Anime rows depend on.
    """

    state: ResolutionState
    confidence: Decimal
    note: str
    chosen: Candidate | None
    alternatives: tuple[Candidate, ...]
    unit_kind: UnitKind

    @property
    def title_tmdb_id(self) -> int | None:
        """The id T19 stores as `title.tmdb_id` - the parent's for a second-pass hit, never the season's."""
        return None if self.chosen is None else self.chosen.title_tmdb_id


async def resolve_title(client: TmdbClient, request: ResolutionRequest) -> TitleResolution:
    """Resolve one row. Never raises: a provider failure is an unresolved row with the class name recorded."""
    try:
        return await _resolved(client, request)
    except ProviderError as error:
        note = PROVIDER_NOTE_TEMPLATE.format(error=f"{type(error).__name__}: {_echoed(str(error))}")
        return _unresolved(request, note)


class TitleResolver:
    """`resolve_title` with the client bound, for a caller that resolves many rows against one client."""

    def __init__(self, client: TmdbClient) -> None:
        self._client = client

    async def resolve(self, request: ResolutionRequest) -> TitleResolution:
        return await resolve_title(self._client, request)


@dataclass(slots=True)
class _Seen:
    """What the searches turned up, so the later passes and the note need no second search to use it."""

    # The best series hit whose title is the front of this row's - the lead the second pass follows.
    parent: Candidate | None = None
    # The best-scoring candidate that was refused, so an unresolved row can say what was rejected and why.
    rejected: tuple[Candidate, str] | None = None


async def _resolved(client: TmdbClient, request: ResolutionRequest) -> TitleResolution:
    seen = _Seen()
    for media_type in request.search_media_types:
        for form, query in _query_forms(request):
            page = await _searched(client, media_type, form, request)
            found = _accepted(request, form, query, page, media_type, seen)
            if found is not None:
                return found
    return await _second_pass(client, request, seen)


def _query_forms(request: ResolutionRequest) -> tuple[tuple[ResolutionRequest, str | None], ...]:
    """The bare title then this category's franchise forms, each as a request of its own; `None` is the bare one.

    A form is dropped when its normalised key repeats an earlier one, and when the prefix it would add is
    already on the front of the title - "Attack On Titan: Attack on Titan: Ilse's Notebook" is a wasted call.
    """
    bare = request.query_title
    if not normalise_title(bare):
        # A row with no title asks nothing. Expanding it would search for the franchise prefix alone, which
        # answers with the franchise - a confident match for a row that named nothing at all.
        return ()
    forms: list[tuple[ResolutionRequest, str | None]] = []
    keys: set[str] = set()
    for expanded in franchise_candidates(request.category_slug, request.category_name, bare):
        key = normalise_title(expanded)
        if not key or key in keys or (expanded != bare and _prefix_already_there(bare, expanded)):
            continue
        keys.add(key)
        forms.append((replace(request, raw_title=expanded), None if expanded == bare else expanded))
    return tuple(forms)


def _prefix_already_there(title: str, expanded: str) -> bool:
    """Whether the franchise words a template would add are already the first words of the title.

    A template that does not simply sit in front of the title leaves `removesuffix` with the whole expanded
    form, which carries the title inside it and so can never be the title's own prefix - the answer is then
    `False` without a branch of its own.
    """
    prefix = normalise_title(expanded.removesuffix(title))
    key = normalise_title(title)
    return bool(prefix) and (key == prefix or key.startswith(f"{prefix} "))


async def _searched(
    client: TmdbClient, media_type: TmdbMediaType, form: ResolutionRequest, request: ResolutionRequest
) -> TmdbSearchPage:
    """One search. A film search is narrowed by the year; a series search deliberately is not.

    `first_air_date_year` filters on when the SERIES began, and a curated TV row is dated by the span it
    names: Inuyasha's "The Final Act" row reads 2009 and the series first aired in 2000, so narrowing would
    return an empty page for it.
    """
    if media_type == MOVIE:
        return await client.search_movie(form.query_title, year=request.year)
    return await client.search_tv(form.query_title)


def _accepted(
    request: ResolutionRequest,
    form: ResolutionRequest,
    query: str | None,
    page: TmdbSearchPage,
    media_type: TmdbMediaType,
    seen: _Seen,
) -> TitleResolution | None:
    """Score this page against this query form, verify in score order, and decide - or record what failed."""
    verified: list[Candidate] = []
    for hit in page.results:
        candidate = Candidate.from_search_hit(hit, media_type)
        scored = replace(candidate, score=score_candidate(form, candidate))
        accepted, reason = verify(form, scored)
        if accepted:
            verified.append(scored)
        else:
            _reject(seen, scored, reason)
        _observe(seen, request, candidate, media_type)
    return _decided(request, form, query, verified) if verified else None


def _decided(
    request: ResolutionRequest, form: ResolutionRequest, query: str | None, verified: list[Candidate]
) -> TitleResolution:
    ordered = _ordered(verified)
    best = ordered[0]
    tied = [candidate for candidate in ordered if candidate.score == best.score]
    if len(tied) > 1:
        return _ambiguous(request, tied)
    alternatives = tuple(ordered[1 : 1 + MAX_ALTERNATIVES])
    why = _why(form, query, best)
    return _resolution(request, best, _confidence(form, query, best), _about(why, best), alternatives)


def _ambiguous(request: ResolutionRequest, tied: list[Candidate]) -> TitleResolution:
    """Equal scores mean the page cannot tell these apart, and the tie-break is arbitrary by construction.

    Persisting one of them would be a coin flip written down as a fact - the failure CLAUDE.md section 18.2
    rule 2 names - so the row goes to a human with every tied candidate on it (Ruling 35). The HunterXHunter
    row that measured this chose the 1999 series over the 2011 one on nothing but the lower TMDB id.
    """
    shown = tied[:MAX_ALTERNATIVES]
    listed = ", ".join(_described(candidate) for candidate in shown)
    if len(tied) > len(shown):
        listed += AND_MORE_TEMPLATE.format(count=len(tied) - len(shown))
    return TitleResolution(
        state=ResolutionState.UNRESOLVED,
        confidence=UNRESOLVED_CONFIDENCE,
        note=AMBIGUOUS_NOTE_TEMPLATE.format(count=len(tied), listed=listed),
        chosen=None,
        # No `chosen`, but the candidates are still the answer's shortlist: the review queue picks one.
        alternatives=tuple(shown),
        unit_kind=request.finalised_unit_kind(None),
    )


def _confidence(form: ResolutionRequest, query: str | None, candidate: Candidate) -> Decimal:
    if query is not None or title_match(form, candidate) is not TitleMatch.EXACT:
        return WEAKER_TITLE_CONFIDENCE
    if year_agreement(form, candidate) is YearAgreement.AGREES:
        return EXACT_WITH_YEAR_CONFIDENCE
    return EXACT_WITHOUT_YEAR_CONFIDENCE


def _why(form: ResolutionRequest, query: str | None, candidate: Candidate) -> str:
    base = _matched_because(form, candidate)
    return base if query is None else f"{base}, {THROUGH_QUERY_TEMPLATE.format(query=_echoed(query))}"


def _matched_because(form: ResolutionRequest, candidate: Candidate) -> str:
    match = title_match(form, candidate)
    if match is TitleMatch.CONTAINED:
        return CONTAINED_NOTE_TEMPLATE.format(name=_echoed(candidate.name))
    if match is TitleMatch.EXTENDED:
        return EXTENDED_NOTE_TEMPLATE.format(name=_echoed(candidate.name))
    year = year_agreement(form, candidate)
    if year is YearAgreement.AGREES:
        return EXACT_WITH_YEAR_NOTE
    # Only a series reaches here with a year that disagrees - a film's would have been rejected - and
    # saying "no release year" about a row that has one would be a lie about why it was not used.
    return UNUSED_YEAR_NOTE if year is YearAgreement.DISAGREES else EXACT_WITHOUT_YEAR_NOTE


async def _second_pass(client: TmdbClient, request: ResolutionRequest, seen: _Seen) -> TitleResolution:
    """Inside a matched parent series: its season names, then its season-zero episode names."""
    if request.expected_media_type == MOVIE:
        return _unresolved(request, _failure(seen))
    parent = seen.parent or await _parent_of(client, request)
    details = None if parent is None else await client.tv_details(parent.tmdb_id)
    if details is None:
        return _unresolved(request, _failure(seen))
    remainder = _remainder(request.query_key, normalise_title(details.name))
    season = _matched_name(details.seasons, remainder, lambda summary: summary.name)
    if season is not None:
        note = SEASON_NOTE_TEMPLATE.format(season=season.season_number, name=_echoed(season.name), parent=details.id)
        unit = MatchedUnit(season_number=season.season_number, episode_number=None, name=season.name)
        return _inside(request, details, note, unit=unit, tmdb_id=season.id, episode_count=season.episode_count)
    # A series with no specials bucket is never asked for one, and a bucket the cache says has not moved
    # answers `None`. Both mean the same thing here - no episode to match - so both take the one way out.
    specials = await _specials_of(client, details)
    episode = None if specials is None else _matched_name(specials.episodes, remainder, lambda entry: entry.name)
    if episode is None:
        return _unresolved(request, _failure(seen))
    note = EPISODE_NOTE_TEMPLATE.format(
        season=episode.season_number, episode=episode.episode_number, name=_echoed(episode.name), parent=details.id
    )
    unit = MatchedUnit(season_number=episode.season_number, episode_number=episode.episode_number, name=episode.name)
    return _inside(request, details, note, unit=unit, tmdb_id=episode.id, episode_count=None)


async def _specials_of(client: TmdbClient, details: TmdbTv) -> TmdbSeason | None:
    """Season zero with its episodes, or `None` when this series has no specials bucket to ask about."""
    has_specials = any(summary.season_number == SPECIALS_SEASON for summary in details.seasons)
    return await client.season_details(details.id, SPECIALS_SEASON) if has_specials else None


def _inside(
    request: ResolutionRequest,
    parent: TmdbTv,
    note: str,
    *,
    unit: MatchedUnit,
    tmdb_id: int,
    episode_count: int | None,
) -> TitleResolution:
    """A season or episode of `parent`, as a candidate whose NAME AND YEAR are the parent's.

    The title row T19 writes is the series, so `name`, `year` and `title_tmdb_id` all describe it; which
    season or episode was matched is `matched_unit`, and `tmdb_id` is that unit's own id (Ruling 33).
    """
    chosen = Candidate(
        media_type=TV,
        tmdb_id=tmdb_id,
        name=parent.name,
        year=release_year(parent.first_air_date or ""),
        runtime_minutes=None,
        episode_count=episode_count,
        parent_tmdb_id=parent.id,
        matched_unit=unit,
        score=SECOND_PASS_CONFIDENCE,
    )
    return _resolution(request, chosen, SECOND_PASS_CONFIDENCE, note, ())


async def _parent_of(client: TmdbClient, request: ResolutionRequest) -> Candidate | None:
    """One series search for the title's own leading segment, else for the category's franchise name."""
    query = _parent_query(request)
    if query is None:
        return None
    form = replace(request, raw_title=query)
    page = await client.search_tv(query)
    # Only an exact title match may stand in as a parent: descending into the wrong series would produce a
    # confident season number for a work that is not in it.
    exact = [
        replace(candidate, score=score_candidate(form, candidate))
        for candidate in (Candidate.from_search_hit(hit, TV) for hit in page.results)
        if title_match(form, candidate) is TitleMatch.EXACT
    ]
    return _ordered(exact)[0] if exact else None


def _parent_query(request: ResolutionRequest) -> str | None:
    """The words before the title's first colon, else the category's franchise name; `None` when neither adds to it."""
    head = request.query_title.split(TITLE_SEGMENT_SEPARATOR, 1)[0].strip()
    franchise = request.category_name.replace(FRANCHISE_WORD_SEPARATOR, " ").strip()
    for query in (head, franchise):
        key = normalise_title(query)
        if key and key != request.query_key:
            return query
    return None


def _remainder(query_key: str, parent_key: str) -> str:
    """What the row's title says beyond the parent's name, renormalised so a leading article is dropped."""
    if parent_key and query_key.startswith(f"{parent_key} "):
        return normalise_title(query_key[len(parent_key) :])
    return query_key


def _matched_name[ItemT](items: Iterable[ItemT], remainder: str, name_of: Callable[[ItemT], str]) -> ItemT | None:
    """The item whose name is the remainder, or - with two tokens or more to go on - begins with it."""
    if not remainder:
        return None
    named = [(item, normalise_title(name_of(item))) for item in items]
    exact = next((item for item, key in named if key == remainder), None)
    if exact is not None or len(remainder.split()) < SECOND_PASS_MINIMUM_TOKENS:
        return exact
    return next((item for item, key in named if key.startswith(f"{remainder} ")), None)


def _about(why: str, chosen: Candidate) -> str:
    """A top-level match's note: why it matched, then which work it matched - the two are separate facts."""
    return CHOSEN_NOTE_TEMPLATE.format(why=why, description=_described(chosen))


def _resolution(
    request: ResolutionRequest,
    chosen: Candidate,
    confidence: Decimal,
    note: str,
    alternatives: tuple[Candidate, ...],
) -> TitleResolution:
    return TitleResolution(
        state=ResolutionState.AUTO,
        confidence=confidence,
        note=note,
        chosen=chosen,
        alternatives=alternatives,
        unit_kind=request.finalised_unit_kind(chosen.media_type),
    )


def _unresolved(request: ResolutionRequest, note: str) -> TitleResolution:
    return TitleResolution(
        state=ResolutionState.UNRESOLVED,
        confidence=UNRESOLVED_CONFIDENCE,
        note=note,
        chosen=None,
        alternatives=(),
        unit_kind=request.finalised_unit_kind(None),
    )


def _failure(seen: _Seen) -> str:
    """Why nothing resolved: the best hit that was refused and the rule that refused it, or that there was none."""
    if seen.rejected is None:
        return NOTHING_MATCHED_NOTE
    candidate, reason = seen.rejected
    return REJECTED_NOTE_TEMPLATE.format(description=_described(candidate), reason=reason)


def _reject(seen: _Seen, candidate: Candidate, reason: str) -> None:
    if seen.rejected is None or candidate.score > seen.rejected[0].score:
        seen.rejected = (candidate, reason)


def _observe(seen: _Seen, request: ResolutionRequest, candidate: Candidate, media_type: TmdbMediaType) -> None:
    """Keep the one lead the second pass needs, judged against the bare title rather than the form's."""
    if media_type != TV:
        return
    scored = replace(candidate, score=score_candidate(request, candidate))
    if title_match(request, scored) in PARENT_LIKE_MATCHES and _better(scored, seen.parent):
        seen.parent = scored


def _better(candidate: Candidate, standing: Candidate | None) -> bool:
    if standing is None:
        return True
    return (-candidate.score, candidate.tmdb_id) < (-standing.score, standing.tmdb_id)


def _ordered(candidates: list[Candidate]) -> list[Candidate]:
    """Score descending, then the lower TMDB id - a tie-break that is deterministic and is not popularity."""
    return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.tmdb_id))


def _described(candidate: Candidate) -> str:
    return DESCRIPTION_TEMPLATE.format(
        media_type=candidate.media_type,
        tmdb_id=candidate.tmdb_id,
        name=_echoed(candidate.name),
        year=candidate.year,
    )


def _echoed(literal: str) -> str:
    """Provider text as a note may carry it: control characters stripped, clipped to a bounded echo."""
    return _CONTROL_CHARACTERS.sub("", literal.strip())[:MAX_NOTE_LITERAL]
