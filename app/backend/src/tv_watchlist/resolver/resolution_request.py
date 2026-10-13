"""One curated row as the resolver reads it: the sheet's own cells, plus the span T17 read out of them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from tv_watchlist.data.enums import UnitKind
from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType
from tv_watchlist.resolver.match_key import normalise_title, release_year, strip_positional_suffix
from tv_watchlist.resolver.span import (
    BLANK_UNIT_NOTE,
    EPISODIC_KINDS,
    TYPE_EPISODIC_CELLS,
    TYPE_MOVIE_CELLS,
    SpanParse,
)

MOVIE: Final[TmdbMediaType] = "movie"
TV: Final[TmdbMediaType] = "tv"
# Films first, for a row that states no kind at all: the library's blank and unparsed units are films far
# more often than series, and a series a film search misses is still reachable through the second pass,
# which searches for its parent anyway.
BOTH_MEDIA_TYPES: Final[tuple[TmdbMediaType, ...]] = (MOVIE, TV)


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """What one row asks the catalogue. `expected_runtime_minutes` is `None` for every sheet today."""

    category_slug: str
    category_name: str
    raw_title: str
    raw_unit: str
    raw_release: str
    raw_type: str
    span: SpanParse
    # No workbook carries a runtime column, so this is `None` in production and the runtime gate in
    # `verification` never fires. It exists because the gate is only meaningful with both sides known,
    # and because a sheet that grows the column should need no new field to use it.
    expected_runtime_minutes: int | None = None

    @property
    def query_title(self) -> str:
        """The title as both query and match key: a trailing "Part N" indexes the row, it does not name it."""
        return strip_positional_suffix(self.raw_title)[0].strip()

    @property
    def query_key(self) -> str:
        """The normalised form every title comparison runs on."""
        return normalise_title(self.query_title)

    @property
    def year(self) -> int | None:
        """The leading year of the `Release` cell, or `None`; the cell itself is never coerced to a date."""
        return release_year(self.raw_release)

    @property
    def kind_is_provisional(self) -> bool:
        """Ruling 27: a blank `Unit` states no kind, so only the matched media type can settle it."""
        return self.span.note == BLANK_UNIT_NOTE

    @property
    def expected_media_type(self) -> TmdbMediaType | None:
        """What the row says it is; `None` means it does not say, and either answer is permissible."""
        # The Type cell first, because it states a shape outright where a unit string may only imply one.
        # It is folded with `normalise_title` rather than a second normaliser: measured over all 57 distinct
        # Type cells in the library, that agrees with the folding `span` applies to the same cells.
        folded = normalise_title(self.raw_type)
        if folded in TYPE_MOVIE_CELLS:
            return MOVIE
        if folded in TYPE_EPISODIC_CELLS:
            return TV
        if self.kind_is_provisional:
            return None
        if self.span.unit_kind is UnitKind.MOVIE:
            return MOVIE
        return TV if self.span.unit_kind in EPISODIC_KINDS else None

    @property
    def search_media_types(self) -> tuple[TmdbMediaType, ...]:
        """Which endpoints this row may be searched on, in the order they are tried."""
        expected = self.expected_media_type
        return BOTH_MEDIA_TYPES if expected is None else (expected,)

    def finalised_unit_kind(self, media_type: TmdbMediaType | None) -> UnitKind:
        """Ruling 27: a provisional kind follows the match (movie -> movie, tv -> series); a stated one stands."""
        if not self.kind_is_provisional or media_type is None:
            return self.span.unit_kind
        return UnitKind.MOVIE if media_type == MOVIE else UnitKind.SERIES
