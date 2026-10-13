"""What one dry run measured, rendered as the durable Markdown the Phase 1 gate reads.

Pure: it takes counts and returns text. Nothing here opens a workbook, calls a provider or writes a
file, so the numbers in `docs/resolver-dry-run.md` can be re-rendered from a tally without spending
another ~2,400 live TMDB calls to learn them again.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Final

ROWS_COLUMN: Final[str] = "rows"
CONFIRMED_COLUMN: Final[str] = "confirmed"
AUTO_RESOLVED_COLUMN: Final[str] = "auto-resolved"
UNRESOLVED_COLUMN: Final[str] = "unresolved"
TALLY_TABLE_HEADER: Final[str] = (
    f"| Workbook | {ROWS_COLUMN} | {CONFIRMED_COLUMN} | {AUTO_RESOLVED_COLUMN} | {UNRESOLVED_COLUMN} |"
)
TALLY_TABLE_SEPARATOR: Final[str] = "| --- | ---: | ---: | ---: | ---: |"
RUNG_TABLE_HEADER: Final[str] = "| confidence | rows |"
RUNG_TABLE_SEPARATOR: Final[str] = "| ---: | ---: |"
WORST_TABLE_HEADER: Final[str] = "| position | title | unit | confidence | note |"
WORST_TABLE_SEPARATOR: Final[str] = "| ---: | --- | --- | ---: | --- |"

MEASURED_ON_LABEL: Final[str] = "measured on"
RESOLVER_LABEL: Final[str] = "resolver"
TOTAL_LABEL: Final[str] = "**Total**"

TITLE_LINE: Final[str] = "# Resolver dry run"
TALLY_HEADING: Final[str] = "## Rows by resolution state"
RUNG_HEADING: Final[str] = "## Rows by confidence"
WORST_HEADING: Final[str] = "## Worst-confidence examples"
WORKBOOK_HEADING_PREFIX: Final[str] = "### "

PREAMBLE: Final[tuple[str, ...]] = (
    "Every row of every workbook in the library, read through the same columns the ingest reads and",
    "resolved by the same resolver, against the live TMDB catalogue. Nothing was written: no workbook",
    "was opened for writing, no row reached Postgres, and no artwork, `changes` or season call was made.",
    "",
    "`confirmed` is always 0. The resolver never awards it - a human does, in the review queue (T30) -",
    "and the column is reported so the set matches the gate.",
)
WORST_PREAMBLE: Final[tuple[str, ...]] = (
    "Ascending by confidence, then by sheet position. Every unresolved row scores 0.00, so for a",
    "workbook holding more than a handful of them these are its lowest-numbered rows, not its worst;",
    "the note beside each one is what says why it did not resolve.",
)

LINE_SEPARATOR: Final[str] = "\n"
ROW_OPEN: Final[str] = "| "
ROW_CLOSE: Final[str] = " |"
CELL_SEPARATOR: Final[str] = " | "
PIPE: Final[str] = "|"
ESCAPED_PIPE: Final[str] = r"\|"
BACKSLASH: Final[str] = "\\"
ESCAPED_BACKSLASH: Final[str] = r"\\"
PERCENT: Final[int] = 100
SUMMARY_TEMPLATE: Final[str] = (
    "{auto} of {rows} rows across {workbooks} workbooks resolved automatically ({share}%); "
    "{unresolved} are left for the review queue."
)


@dataclass(frozen=True, slots=True)
class WorstExample:
    """One row the resolver was least sure of, with the cells it was reading and the reason it gave."""

    position: int
    raw_title: str
    raw_unit: str
    confidence: Decimal
    note: str


@dataclass(frozen=True, slots=True)
class WorkbookTally:
    """One workbook's measurement.

    `unresolved` is the residual `rows - confirmed - auto_resolved`, computed the same way
    `WatchCounts.unwatched` is, so the four columns are always internally consistent. `rungs` carries
    the whole confidence distribution - truncating to `worst` alone would leave a question like "how
    many rows scored 0.50?" answerable only by spending the live calls again.
    """

    category_name: str
    rows: int
    confirmed: int
    auto_resolved: int
    unresolved: int
    worst: tuple[WorstExample, ...] = ()
    rungs: tuple[tuple[Decimal, int], ...] = field(default=())


def _cell(value: str) -> str:
    """One table cell: no newline may split the row in two, and no pipe may forge a column."""
    # Backslashes go first. Escaping only the pipe puts a backslash in front of a backslash the value
    # already carried, and that pair is itself an escape - leaving the pipe behind it free to open a
    # column after all. The same two-step `services/attribution.py` does for the artwork table.
    flattened = " ".join(value.split()).replace(BACKSLASH, ESCAPED_BACKSLASH)
    return flattened.replace(PIPE, ESCAPED_PIPE)


def _row(*cells: str) -> str:
    return ROW_OPEN + CELL_SEPARATOR.join(_cell(cell) for cell in cells) + ROW_CLOSE


def _tally_row(label: str, rows: int, confirmed: int, auto_resolved: int, unresolved: int) -> str:
    return _row(label, str(rows), str(confirmed), str(auto_resolved), str(unresolved))


def _share(part: int, whole: int) -> int:
    """A whole-number percentage, guarded like `progressPercent` against an empty library."""
    return 0 if whole == 0 else round(part / whole * PERCENT)


def _tally_table(tallies: Sequence[WorkbookTally]) -> list[str]:
    lines = [TALLY_TABLE_HEADER, TALLY_TABLE_SEPARATOR]
    lines.extend(
        _tally_row(tally.category_name, tally.rows, tally.confirmed, tally.auto_resolved, tally.unresolved)
        for tally in tallies
    )
    lines.append(
        _tally_row(
            TOTAL_LABEL,
            sum(tally.rows for tally in tallies),
            sum(tally.confirmed for tally in tallies),
            sum(tally.auto_resolved for tally in tallies),
            sum(tally.unresolved for tally in tallies),
        )
    )
    return lines


def _rung_table(tallies: Sequence[WorkbookTally]) -> list[str]:
    """The library-wide confidence distribution, best rung first."""
    counted: Counter[Decimal] = Counter()
    for tally in tallies:
        for confidence, count in tally.rungs:
            counted[confidence] += count
    if not counted:
        return []
    lines = [RUNG_HEADING, "", RUNG_TABLE_HEADER, RUNG_TABLE_SEPARATOR]
    lines.extend(_row(str(confidence), str(counted[confidence])) for confidence in sorted(counted, reverse=True))
    lines.append("")
    return lines


def _worst_tables(tallies: Sequence[WorkbookTally]) -> list[str]:
    shown = [tally for tally in tallies if tally.worst]
    if not shown:
        return []
    lines = [WORST_HEADING, "", *WORST_PREAMBLE, ""]
    for tally in shown:
        lines.extend([f"{WORKBOOK_HEADING_PREFIX}{tally.category_name}", "", WORST_TABLE_HEADER, WORST_TABLE_SEPARATOR])
        lines.extend(
            _row(str(example.position), example.raw_title, example.raw_unit, str(example.confidence), example.note)
            for example in sorted(tally.worst, key=lambda example: (example.confidence, example.position))
        )
        lines.append("")
    return lines


def render_report(tallies: Sequence[WorkbookTally], *, measured_on: date, resolver_version: str) -> str:
    """The whole report: what was measured and when, the four-column tally, the rungs, the worst rows."""
    rows = sum(tally.rows for tally in tallies)
    auto_resolved = sum(tally.auto_resolved for tally in tallies)
    summary = SUMMARY_TEMPLATE.format(
        auto=auto_resolved,
        rows=rows,
        workbooks=len(tallies),
        share=_share(auto_resolved, rows),
        unresolved=sum(tally.unresolved for tally in tallies),
    )
    lines = [
        TITLE_LINE,
        "",
        f"{MEASURED_ON_LABEL}: {measured_on.isoformat()}",
        f"{RESOLVER_LABEL}: {resolver_version}",
        "",
        *PREAMBLE,
        "",
        summary,
        "",
        TALLY_HEADING,
        "",
        *_tally_table(tallies),
        "",
        *_rung_table(tallies),
        *_worst_tables(tallies),
    ]
    # LF only, no trailing whitespace on any line, one trailing newline.
    return LINE_SEPARATOR.join(line.rstrip() for line in lines).rstrip() + LINE_SEPARATOR
