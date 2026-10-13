"""Which of a sheet's own columns carry the title, the unit, the release and the type.

A schema question, so it lives beside `schema.py` whose folding it reuses rather than in any one of its
callers: the reconciler and the resolver's dry run both ask it, and neither owns the answer (Ruling 39).

Found by role and by normalised header alias, never by position and never by the literal header text: the
nineteen workbooks head the same concept nine different ways, and four of them head one or more of these
concepts not at all. WWII's third column is `Event` - the historical event a film depicts, not a unit of
that film - and every one of Misc_Movies' rows carries nothing but `Order` and `Title`. Both are normal
(CLAUDE.md section 18.2), so a column that is absent reads as an empty string rather than a guess.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tv_watchlist.constants import RELEASE_HEADER_ALIASES, TYPE_HEADER_ALIASES, UNIT_HEADER_ALIASES
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.workbook.naming import slugify
from tv_watchlist.workbook.schema import normalize_header


def header_alias(label: str) -> str:
    """The header as an alias set spells it: `normalize_header`, with its runs of spaces collapsed.

    `normalize_header` deletes punctuation rather than replacing it, so "Season / Unit" comes back with
    two spaces in the middle. Collapsing here keeps the aliases readable instead of spelling that quirk
    out in `constants.py`, and keeps this the only place the two-step folding lives.
    """
    return " ".join(normalize_header(label).split())


def _aliased(columns: Sequence[ColumnSpec], aliases: frozenset[str]) -> ColumnSpec | None:
    return next((column for column in columns if header_alias(column.label) in aliases), None)


def _text(column: ColumnSpec | None, row: WatchRow) -> str:
    return "" if column is None else row.cells.get(column.key, "")


@dataclass(frozen=True, slots=True)
class CuratedColumns:
    """The four columns the resolver reads, each `None` when this sheet does not carry it."""

    title: ColumnSpec | None
    unit: ColumnSpec | None
    release: ColumnSpec | None
    type: ColumnSpec | None

    def raw_title(self, row: WatchRow) -> str:
        return _text(self.title, row)

    def raw_unit(self, row: WatchRow) -> str:
        return _text(self.unit, row)

    def raw_release(self, row: WatchRow) -> str:
        return _text(self.release, row)

    def raw_type(self, row: WatchRow) -> str:
        return _text(self.type, row)


def raw_type_cell(cells: Mapping[str, str]) -> str:
    """The Type/Format cell of a row read back out of `curated_entry.raw_cells`, or `""` when it has none.

    The stored row carries no `ColumnSpec` list, so the alias set is slugified to the keys `unique_key`
    minted rather than compared against header text that is no longer on hand - both foldings delete or
    replace the same punctuation, so "Release Date" and "release date" reach the same key either way.
    The aliases are walked in sorted order because a frozenset has no order and a row that carried both
    headers would otherwise answer differently between runs.
    """
    for alias in sorted(TYPE_HEADER_ALIASES):
        found = cells.get(slugify(alias), "")
        if found:
            return found
    return ""


def curated_columns(columns: Sequence[ColumnSpec]) -> CuratedColumns:
    """Read one sheet's schema for the four columns a curated row is resolved from."""
    return CuratedColumns(
        title=next((column for column in columns if column.role == "title"), None),
        unit=_aliased(columns, UNIT_HEADER_ALIASES),
        release=_aliased(columns, RELEASE_HEADER_ALIASES),
        type=_aliased(columns, TYPE_HEADER_ALIASES),
    )
