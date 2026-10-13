"""The `Unit` grammar: one hand-written span string read into a span, or refused with a reason."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from tv_watchlist.data.enums import OrderType, UnitKind
from tv_watchlist.resolver.match_key import DASH_CHARACTERS

# The one numbering this grammar can read out of a cell. `SpanParse.order_type` stays a plain `str`
# rather than `OrderType`, because TheTVDB's season types are read at runtime and the set is open
# (master plan section 10.1) - this constant names the one a *string* can state, nothing more. The
# season-scoped shape deliberately names none: see SEASON_SCOPED_NOTE.
ABSOLUTE_ORDER: Final[str] = OrderType.ABSOLUTE.value

# 1.00 is reserved for the closed vocabulary that states its own kind outright - a bare Movie, a
# numbered Movie, a Film. Everything else stakes something on a reading the resolver has to confirm,
# and says so. A blank cell is not in that set: it states nothing at all.
MOVIE_CONFIDENCE: Final[Decimal] = Decimal("1.00")
EPISODE_CONFIDENCE: Final[Decimal] = Decimal("0.90")
SPECIAL_CONFIDENCE: Final[Decimal] = Decimal("0.70")
SHORT_CONFIDENCE: Final[Decimal] = Decimal("0.60")
# A season-scoped range stakes its correctness on the season number, so it is capped where a bare
# season is: episodes 10 to 19 *of season 5* are the right episodes only if the sheet's season 5 is
# the provider's.
SEASON_CONFIDENCE: Final[Decimal] = Decimal("0.50")
# A blank cell is read from the Type/Format column, which is a weaker source than the unit string.
# Only the TMDB match can raise this, and that is T18's to award.
BLANK_UNIT_CONFIDENCE: Final[Decimal] = Decimal("0.50")
SEASON_RANGE_CONFIDENCE: Final[Decimal] = Decimal("0.40")
UNPARSED_CONFIDENCE: Final[Decimal] = Decimal("0.00")

ABSOLUTE_ASSUMED_NOTE: Final[str] = "absolute numbering assumed; verified against the title's orders at resolution"
SHORT_NOTE: Final[str] = "short: confirm the TMDB entry type"
SPECIAL_NOTE: Final[str] = "special: span unknown until matched inside the parent"
SEASON_NOTE: Final[str] = (
    "a marketing season may not be the production season (Pokémon: Indigo League is not TMDB season 1)"
)
SEASON_SCOPED_NOTE: Final[str] = (
    "episode numbers scoped to the sheet's season; the numbering may be within-season or series-wide "
    "- confirm against the title's orders"
)
SEASON_RANGE_NOTE: Final[str] = "season range: confirm by hand"
BLANK_UNIT_NOTE: Final[str] = "kind follows the resolved title's media type; confirm at TMDB match"
REVERSED_SPAN_NOTE: Final[str] = "reversed span"
BELOW_MINIMUM_NOTE: Final[str] = "span numbered below the minimum"
UNPARSED_NOTE_TEMPLATE: Final[str] = "unparsed: {literal}"
TYPE_DISAGREEMENT_TEMPLATE: Final[str] = 'unit "{unit}" reads as {kind} but the type cell says "{raw_type}"'

# A curated span never counts from zero; season 0 is a real bucket, so seasons start lower.
MINIMUM_EPISODE_NUMBER: Final[int] = 1
MINIMUM_SEASON_NUMBER: Final[int] = 0
# Caps so a nonsense run of digits falls out as unparsed rather than becoming a span of 10**400.
# One Piece reaches E1176, so four digits is the library's ceiling and five is the headroom.
MAX_EPISODE_DIGITS: Final[int] = 5
MAX_SEASON_DIGITS: Final[int] = 3
MAX_INSTALMENT_DIGITS: Final[int] = 3
# A refusal echoes the cell so the review queue shows what the sheet says, which makes the cell an
# untrusted string in a note the ingest logs (CLAUDE.md section 10.3, B14). Bound it and strip the
# control characters that would forge a log line. This does not import `models.cell_text`: the
# resolver takes no dependency outside `data/enums` and its own package.
MAX_NOTE_LITERAL: Final[int] = 200
_CONTROL_CHARACTERS: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\r\n]")

ASCII_DASH: Final[str] = "-"
_DASH_TABLE: Final[dict[int, str]] = {ord(character): ASCII_DASH for character in DASH_CHARACTERS}

# Longest first: leftmost-alternation would let "E" win on "Episodes 19-53" and force a backtrack.
_EPISODE_WORD: Final[str] = r"(?:Episodes|Episode|Ep\.?|E)"
_SEASON_WORD: Final[str] = r"(?:Season|S)"
_EPISODE_NUMBER: Final[str] = rf"(\d{{1,{MAX_EPISODE_DIGITS}}})"
_SEASON_NUMBER: Final[str] = rf"(\d{{1,{MAX_SEASON_DIGITS}}})"
_RANGE_TAIL: Final[str] = rf"(?:\s*{ASCII_DASH}\s*{_EPISODE_NUMBER})?"

# Every unit the grammar recognises, matched in this order against the folded cell. The order is
# load-bearing twice: a season-scoped range must be tried before a bare season or a bare episode
# range, and a plural "Seasons 1-25" before the singular "Season 1".
_SEASON_SCOPED = re.compile(
    rf"{_SEASON_WORD}\s*{_SEASON_NUMBER}\s*{_EPISODE_WORD}\s*{_EPISODE_NUMBER}{_RANGE_TAIL}", re.IGNORECASE
)
_SEASON_RANGE = re.compile(rf"Seasons\s*{_SEASON_NUMBER}\s*{ASCII_DASH}\s*{_SEASON_NUMBER}", re.IGNORECASE)
_SEASON = re.compile(rf"{_SEASON_WORD}\s*{_SEASON_NUMBER}", re.IGNORECASE)
_EPISODE_RANGE = re.compile(rf"{_EPISODE_WORD}\s*{_EPISODE_NUMBER}{_RANGE_TAIL}", re.IGNORECASE)
_MOVIE = re.compile(rf"(?:Movie|Film)(?:\s*\d{{1,{MAX_INSTALMENT_DIGITS}}}[A-Z]?)?", re.IGNORECASE)
_SHORT = re.compile(r"(?:Movie\s+short|Shorts?|Short\s+film)", re.IGNORECASE)
_SPECIAL = re.compile(
    rf"(?:OVA\s+collection|OVA|OAD|ONA|TV\s+Special|Special)(?:\s*\d{{1,{MAX_INSTALMENT_DIGITS}}})?", re.IGNORECASE
)

# The Type/Format cell vetoes a parse the unit string made, and supplies the kind when the unit
# string made none. Only cells that state a shape beyond doubt belong here: "Anime", "Animation",
# "Crossover" and "Live-action" say nothing about episode count and are deliberately absent, because
# a veto fired on an ambiguous word would refuse correct parses.
TYPE_MOVIE_CELLS: Final[frozenset[str]] = frozenset(
    {
        "movie",
        "film",
        "tv movie",
        "tv film",
        "live action movie",
        "animated movie",
        "cg movie",
        "compilation movie",
        "anime feature",
    }
)
TYPE_EPISODIC_CELLS: Final[frozenset[str]] = frozenset(
    {
        "tv",
        "series",
        "live action tv",
        "animated tv",
        "tv miniseries",
        "miniseries",
        "spin off tv",
        "tv spin off",
        "tv side series",
    }
)
EPISODIC_KINDS: Final[frozenset[UnitKind]] = frozenset({UnitKind.EPISODES, UnitKind.SEASON, UnitKind.SERIES})

_NON_ALPHANUMERIC: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SpanParse:
    """One `Unit` cell read into a span, with how far the reading can be trusted and why."""

    unit_kind: UnitKind
    order_type: str | None
    span_start: int | None
    span_end: int | None
    season_number: int | None
    confidence: Decimal
    note: str

    @property
    def episode_span(self) -> tuple[int, int] | None:
        """Episode bounds, only when this parse names episodes. Read this, never `span_start` directly."""
        if self.unit_kind is not UnitKind.EPISODES:
            return None
        return None if self.span_start is None or self.span_end is None else (self.span_start, self.span_end)

    @property
    def season_span(self) -> tuple[int, int] | None:
        """Season bounds of a `Seasons A-B` cell. Read this, never `span_start` directly."""
        if self.unit_kind is not UnitKind.SEASON:
            return None
        return None if self.span_start is None or self.span_end is None else (self.span_start, self.span_end)


def normalise_unit(raw_unit: str) -> str:
    """The comparable form of a `Unit` cell: every dash variant folded to `-`, whitespace collapsed."""
    return " ".join(raw_unit.translate(_DASH_TABLE).split())


def unparsed_note(literal: str) -> str:
    """The note a refused cell carries, so the review queue shows what the sheet actually says."""
    return UNPARSED_NOTE_TEMPLATE.format(literal=_echoed(literal))


def parse_unit(raw_unit: str, *, raw_type: str = "") -> SpanParse:
    """Read a `Unit` cell into a span; never raises, and refuses rather than guessing."""
    folded = normalise_unit(raw_unit)
    # A blank cell makes no claim, so there is nothing for the type cell to contradict: it supplies
    # the kind outright rather than vetoing one.
    if not folded:
        return _blank(raw_type)
    parse = _parsed(folded, raw_unit)
    return _vetoed(parse, raw_unit, raw_type) if _contradicts(parse.unit_kind, raw_type) else parse


def _parsed(folded: str, raw_unit: str) -> SpanParse:
    """`folded` is what the patterns match; `raw_unit` is what a refusal echoes, dashes and all."""
    scoped = _SEASON_SCOPED.fullmatch(folded)
    if scoped:
        return _season_scoped(scoped)
    seasons = _SEASON_RANGE.fullmatch(folded)
    if seasons:
        return _season_range(seasons)
    season = _SEASON.fullmatch(folded)
    if season:
        return _season(season)
    episodes = _EPISODE_RANGE.fullmatch(folded)
    if episodes:
        return _episodes(episodes)
    if _MOVIE.fullmatch(folded):
        return _flat(UnitKind.MOVIE, MOVIE_CONFIDENCE, "")
    if _SHORT.fullmatch(folded):
        return _flat(UnitKind.SPECIAL, SHORT_CONFIDENCE, SHORT_NOTE)
    if _SPECIAL.fullmatch(folded):
        return _flat(UnitKind.SPECIAL, SPECIAL_CONFIDENCE, SPECIAL_NOTE)
    return _refused(unparsed_note(raw_unit))


def _blank(raw_type: str) -> SpanParse:
    """An empty cell: Misc_Movies leaves it blank on a film, Misc_Anime on a series, so the type leads."""
    episodic = _normalise_type(raw_type) in TYPE_EPISODIC_CELLS
    return _flat(UnitKind.SERIES if episodic else UnitKind.MOVIE, BLANK_UNIT_CONFIDENCE, BLANK_UNIT_NOTE)


def _flat(unit_kind: UnitKind, confidence: Decimal, note: str) -> SpanParse:
    """A unit that names no span at all - a film, a series, a short, an OVA, a special."""
    return SpanParse(
        unit_kind=unit_kind,
        order_type=None,
        span_start=None,
        span_end=None,
        season_number=None,
        confidence=confidence,
        note=note,
    )


def _refused(note: str) -> SpanParse:
    return _flat(UnitKind.UNKNOWN, UNPARSED_CONFIDENCE, note)


def _episodes(match: re.Match[str]) -> SpanParse:
    start, end = _bounds(match, 1, 2)
    if not _is_a_span(start, end, MINIMUM_EPISODE_NUMBER):
        return _refused(_reason_for(start, MINIMUM_EPISODE_NUMBER))
    return SpanParse(
        unit_kind=UnitKind.EPISODES,
        order_type=ABSOLUTE_ORDER,
        span_start=start,
        span_end=end,
        season_number=None,
        confidence=EPISODE_CONFIDENCE,
        note=ABSOLUTE_ASSUMED_NOTE,
    )


def _season_scoped(match: re.Match[str]) -> SpanParse:
    """`S5 E10-19`. No order_type: 8 of the library's 53 such rows number series-wide, not per season."""
    start, end = _bounds(match, 2, 3)
    if not _is_a_span(start, end, MINIMUM_EPISODE_NUMBER):
        return _refused(_reason_for(start, MINIMUM_EPISODE_NUMBER))
    return SpanParse(
        unit_kind=UnitKind.EPISODES,
        order_type=None,
        span_start=start,
        span_end=end,
        season_number=int(match.group(1)),
        confidence=SEASON_CONFIDENCE,
        note=SEASON_SCOPED_NOTE,
    )


def _season(match: re.Match[str]) -> SpanParse:
    """A bare season number. It needs no floor check: season 0 is the specials bucket and is kept."""
    return SpanParse(
        unit_kind=UnitKind.SEASON,
        order_type=None,
        span_start=None,
        span_end=None,
        season_number=int(match.group(1)),
        confidence=SEASON_CONFIDENCE,
        note=SEASON_NOTE,
    )


def _season_range(match: re.Match[str]) -> SpanParse:
    start, end = _bounds(match, 1, 2)
    if not _is_a_span(start, end, MINIMUM_SEASON_NUMBER):
        return _refused(_reason_for(start, MINIMUM_SEASON_NUMBER))
    # The span holds season numbers here, not episode numbers, and no order_type: a range of seasons
    # is not a range in any episode numbering, which is exactly why it goes to the queue. Consumers
    # read it through `season_span`, which is None for every other kind.
    return SpanParse(
        unit_kind=UnitKind.SEASON,
        order_type=None,
        span_start=start,
        span_end=end,
        season_number=None,
        confidence=SEASON_RANGE_CONFIDENCE,
        note=SEASON_RANGE_NOTE,
    )


def _bounds(match: re.Match[str], start_group: int, end_group: int) -> tuple[int, int]:
    """A range's two ends; a cell naming one number is the one-long span from it to itself."""
    start = int(match.group(start_group))
    end = match.group(end_group)
    return start, int(end) if end else start


def _is_a_span(start: int, end: int, minimum: int) -> bool:
    return start >= minimum and end >= start


def _reason_for(start: int, minimum: int) -> str:
    """Why a matched range is refused. Both are structural, so neither echoes the cell."""
    return BELOW_MINIMUM_NOTE if start < minimum else REVERSED_SPAN_NOTE


def _contradicts(unit_kind: UnitKind, raw_type: str) -> bool:
    normalised = _normalise_type(raw_type)
    if unit_kind is UnitKind.MOVIE:
        return normalised in TYPE_EPISODIC_CELLS
    if unit_kind in EPISODIC_KINDS:
        return normalised in TYPE_MOVIE_CELLS
    return False


def _normalise_type(raw_type: str) -> str:
    return " ".join(_NON_ALPHANUMERIC.sub(" ", raw_type.casefold()).split())


def _echoed(literal: str) -> str:
    """Cell text as a note may carry it: control characters stripped, clipped to a bounded echo."""
    return _CONTROL_CHARACTERS.sub("", literal.strip())[:MAX_NOTE_LITERAL]


def _vetoed(parse: SpanParse, raw_unit: str, raw_type: str) -> SpanParse:
    """The two cells name different shapes, so neither reading is trusted and both are recorded."""
    return _refused(
        TYPE_DISAGREEMENT_TEMPLATE.format(
            unit=_echoed(raw_unit), kind=parse.unit_kind.value, raw_type=_echoed(raw_type)
        )
    )
