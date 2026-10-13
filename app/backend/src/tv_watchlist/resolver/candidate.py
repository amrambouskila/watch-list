"""One TMDB work a row might resolve to, reduced to the fields that decide whether it does."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType, TmdbSearchHit
from tv_watchlist.resolver.match_key import release_year
from tv_watchlist.resolver.resolution_request import MOVIE

NO_SCORE = Decimal("0")


@dataclass(frozen=True, slots=True)
class MatchedUnit:
    """Which season or episode inside a parent series a row matched. The parent is the title; this is not.

    Kept beside `Candidate` rather than in a module of its own because it is a helper type used by exactly
    one component and meaningless without it (CLAUDE.md section 7, the one sanctioned exception).
    """

    season_number: int
    # `None` for a season match; set when the row matched one episode of the specials bucket.
    episode_number: int | None
    # The season's or episode's own name, which is NOT the title's - `Candidate.name` carries that.
    name: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """A film or series, or - when `matched_unit` is set - a season or episode found inside a series.

    `name` and `year` always describe the TITLE: for a second-pass hit that is the parent series, not the
    season or episode inside it, which `matched_unit` describes instead. `title_tmdb_id` is the id of that
    title and is what T19 stores as `title.tmdb_id`; `tmdb_id` is the id of the work actually matched, so
    for a second-pass hit it is the season's or episode's own.

    There is deliberately no popularity, vote count or TMDB rank field: ordering a page by any of those is
    the failure this resolver exists to avoid, and a field that is absent cannot be read by accident.
    """

    media_type: TmdbMediaType
    tmdb_id: int
    name: str
    year: int | None
    runtime_minutes: int | None
    episode_count: int | None
    parent_tmdb_id: int | None = None
    matched_unit: MatchedUnit | None = None
    # Every other name this work is known by - TMDB's original title, which every search hit carries.
    also_known_as: tuple[str, ...] = ()
    score: Decimal = NO_SCORE

    @property
    def title_tmdb_id(self) -> int:
        """The id of the TITLE row this resolves to: the parent's when it sits inside one, else its own."""
        return self.tmdb_id if self.parent_tmdb_id is None else self.parent_tmdb_id

    @property
    def season_number(self) -> int | None:
        """The matched season, read off `matched_unit` so the two can never disagree."""
        return None if self.matched_unit is None else self.matched_unit.season_number

    @property
    def episode_number(self) -> int | None:
        """The matched episode of the specials bucket, or `None` for every other kind of match."""
        return None if self.matched_unit is None else self.matched_unit.episode_number

    @property
    def names(self) -> tuple[str, ...]:
        """Every name a row's title may be compared against, the primary one first."""
        return (self.name, *self.also_known_as)

    @classmethod
    def from_search_hit(cls, hit: TmdbSearchHit, media_type: TmdbMediaType) -> Candidate:
        """A search result. The endpoint decides the media type: hits from `/search/movie` carry none."""
        is_film = media_type == MOVIE
        original = hit.original_title if is_film else hit.original_name
        name = (hit.title if is_film else hit.name) or ""
        return cls(
            media_type=media_type,
            tmdb_id=hit.id,
            name=name,
            year=release_year(hit.release_date or hit.first_air_date or ""),
            # A search hit carries neither, and neither is worth a details call per hit to learn.
            runtime_minutes=None,
            episode_count=None,
            also_known_as=(original,) if original and original != name else (),
        )
