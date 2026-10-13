"""One TheTVDB ordering's episodes onto the TMDB episodes already stored.

**Never by position.** TMDB numbers anime absolute-continuously inside season buckets - One Piece's
season 2 runs 62-77 - so the nth entry of a TheTVDB ordering is not the nth row of this projection, and
pairing them by position would renumber a whole series while looking perfectly ordered on screen. That
is the worst failure shape available here, so no arm of this matcher counts anything.

**Two arms, both exact, tried in order.** An air date that is unique on *both* sides is the first; the
absolute number answering our own aired rank is the second. Laboon is why the second exists: TMDB and
TheTVDB both aired it on 2001-03-21 and both aired something else that day, so the date arm cannot see
it and only its absolute number - 62, which is also its aired rank - pairs it.

**Both arms are guarded by the air date, because our rank is not the service's number.** The aired rank
is dense over the episodes this projection *holds*, while `absoluteNumber` counts the whole series, so a
gap - a season TMDB answered 404 for, a backoff that has not run out - slides our rank against theirs
and every pair after the gap is confidently wrong. With One Piece's season 1 missing, the second arm
paired TheTVDB's episodes 1-16 with TMDB's 62-77: seven wrong rows per ordering, each one looking
perfectly ordered on screen. So a pair whose two sides both know the day and disagree about it by more
than `_DATE_TOLERANCE_DAYS` is refused. The guard is subtractive only, and its measured cost on the
recorded orderings is zero.

**Everything else is unmatched, counted and named.** There is no third arm, and deliberately no name
arm: episode names cross the two services as romaji, English and synonyms, and generic ones repeat, so
an exact-name pair would add little to these two while risking a silently wrong one.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode

type Candidate = Callable[[TvdbEpisode], uuid.UUID | None]
"""One arm of the pairing: the stored episode this TheTVDB episode identifies, or nothing."""

# TheTVDB writes 0 into `absoluteNumber` for an episode that has none - every special does. A rank is
# 1-based, so the two can never meet, but the intent is stated rather than left to arithmetic.
_NO_ABSOLUTE_NUMBER: int = 0
_APPEARS_ONCE: int = 1
# One day, because the two services record a broadcast in different timezones and a late-night episode
# lands either side of midnight. Anything wider would start admitting the neighbouring week's episode.
_DATE_TOLERANCE_DAYS: int = 1


@dataclass(frozen=True, slots=True)
class StoredEpisode:
    """The three facts a pairing is made on: which row, the day it aired, and where the aired walk put it.

    `aired_rank` is `None` for a special: season 0 is excluded from the aired walk, so a special can
    only ever be paired by its own air date.
    """

    episode_id: uuid.UUID
    air_date: date | None
    aired_rank: int | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Which TheTVDB episodes were paired, with what, by which arm - and which were not paired at all."""

    matched: Mapping[int, uuid.UUID] = field(default_factory=dict)
    unmatched: tuple[int, ...] = ()
    by_air_date: int = 0
    by_absolute_number: int = 0


def aired_on(raw: str | None) -> date | None:
    """TheTVDB's `aired` string as a date. Absent, empty and unparseable are all simply absent.

    Read here rather than in the model: one undated episode must not turn a 500-episode page into a
    validation failure, so the string arrives intact and is interpreted at this boundary.
    """
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _numbered(episode: TvdbEpisode) -> bool:
    """Whether TheTVDB counts this episode in the series' numbered run, rather than beside it.

    `absoluteNumber` is the one marker that travels across orderings: season 0 holds the specials in
    TheTVDB's own aired ordering, but its disc orderings file them in a later season instead.
    """
    return episode.absolute_number is not None and episode.absolute_number > _NO_ABSOLUTE_NUMBER


def match_tvdb_episodes(tvdb_episodes: Sequence[TvdbEpisode], stored: Sequence[StoredEpisode]) -> MatchResult:
    """Pair one ordering with this projection, claiming each stored episode at most once.

    `uq(episode_id, order_type, label)` makes a second claim on one episode unstorable, so a later
    claimant is left unmatched rather than quietly displacing the first.
    """
    here = _dates_appearing_once(episode.air_date for episode in stored)
    there = _dates_appearing_once(aired_on(episode.aired) for episode in tvdb_episodes)
    by_date = {episode.air_date: episode.episode_id for episode in stored if episode.air_date in here}
    by_rank = {episode.aired_rank: episode.episode_id for episode in stored if episode.aired_rank is not None}
    ranks = {episode.episode_id: episode.aired_rank for episode in stored}
    days = {episode.episode_id: episode.air_date for episode in stored}

    def by_air_date(episode: TvdbEpisode) -> uuid.UUID | None:
        day = aired_on(episode.aired)
        if day is None or day not in there:
            return None
        candidate = by_date.get(day)
        # Both sides must agree that this is, or is not, part of the numbered run. A special and a
        # regular episode routinely share a broadcast day, and when this projection holds only some of
        # a series - a season that 404ed, a backoff that has not run out - each of the two can be the
        # only one on its own side and pair with the other. That is a wrong pair that looks right, and
        # it happened here: TheTVDB's One Piece 579 aired the same day as TMDB's "Glorious Island".
        return None if candidate is None or _numbered(episode) != (ranks.get(candidate) is not None) else candidate

    def by_absolute_number(episode: TvdbEpisode) -> uuid.UUID | None:
        if not _numbered(episode):
            return None
        candidate = by_rank.get(episode.absolute_number)
        # The rank is dense over what this projection holds; `absoluteNumber` counts the whole series.
        # A missing season slides one against the other, so the day they both claim has to agree.
        return None if candidate is None or not _days_agree(aired_on(episode.aired), days.get(candidate)) else candidate

    matched: dict[int, uuid.UUID] = {}
    claimed: set[uuid.UUID] = set()
    # Order matters: a date unique on both sides identifies an episode without trusting either
    # service's numbering, so it is tried before the arm that does.
    dated = _claimed(tvdb_episodes, matched, claimed, by_air_date)
    numbered = _claimed(tvdb_episodes, matched, claimed, by_absolute_number)
    return MatchResult(
        matched=matched,
        unmatched=tuple(episode.id for episode in tvdb_episodes if episode.id not in matched),
        by_air_date=dated,
        by_absolute_number=numbered,
    )


def _days_agree(there: date | None, here: date | None) -> bool:
    """Whether two sides that both know the day agree about it. A side that does not know cannot object."""
    if there is None or here is None:
        return True
    return abs((there - here).days) <= _DATE_TOLERANCE_DAYS


def _dates_appearing_once(dates: Iterable[date | None]) -> frozenset[date]:
    """The days exactly one episode of a sequence carries; a day two share identifies neither of them."""
    counted = Counter(day for day in dates if day is not None)
    return frozenset(day for day, seen in counted.items() if seen == _APPEARS_ONCE)


def _claimed(
    tvdb_episodes: Sequence[TvdbEpisode],
    matched: dict[int, uuid.UUID],
    claimed: set[uuid.UUID],
    candidate: Candidate,
) -> int:
    """One arm, over the episodes no earlier arm paired. Returns how many this arm accounted for."""
    made = 0
    for episode in tvdb_episodes:
        if episode.id in matched:
            continue
        stored_id = candidate(episode)
        if stored_id is None or stored_id in claimed:
            continue
        matched[episode.id] = stored_id
        claimed.add(stored_id)
        made += 1
    return made
