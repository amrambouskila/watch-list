"""The dry-run report: what it renders, and that the committed measurement is really there."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from library_choice import every_workbook
from tv_watchlist.resolver.dry_run_report import (
    AUTO_RESOLVED_COLUMN,
    CONFIRMED_COLUMN,
    MEASURED_ON_LABEL,
    ROWS_COLUMN,
    TALLY_TABLE_HEADER,
    TOTAL_LABEL,
    UNRESOLVED_COLUMN,
    WorkbookTally,
    WorstExample,
    render_report,
)

# The repository root, the same way `config.py` reaches it: this file sits at
# TV/app/backend/tests/resolver/, so the fifth parent is TV itself.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
COMMITTED_REPORT: Final[Path] = REPO_ROOT / "docs" / "resolver-dry-run.md"
LIBRARY_ROW_COUNT: Final[int] = 996
LIBRARY_WORKBOOK_COUNT: Final[int] = 19

A_DATE: Final[date] = date(2026, 9, 20)
A_VERSION: Final[str] = "tv-watchlist 0.1.0"


def a_tally(
    name: str,
    *,
    rows: int = 10,
    auto_resolved: int = 7,
    worst: tuple[WorstExample, ...] = (),
    rungs: tuple[tuple[Decimal, int], ...] = (),
) -> WorkbookTally:
    """One workbook's counts, with `unresolved` the residual the runner also computes it as."""
    return WorkbookTally(
        category_name=name,
        rows=rows,
        confirmed=0,
        auto_resolved=auto_resolved,
        unresolved=rows - auto_resolved,
        worst=worst,
        rungs=rungs,
    )


def an_example(position: int, confidence: str, *, note: str = "a reason") -> WorstExample:
    return WorstExample(
        position=position,
        raw_title=f"Title {position}",
        raw_unit="Movie",
        confidence=Decimal(confidence),
        note=note,
    )


def data_rows_of(report: str) -> list[str]:
    """The tally table's rows, without its header, its separator or its totals line."""
    lines = report.splitlines()
    start = lines.index(TALLY_TABLE_HEADER) + 2
    body = lines[start:]
    end = next((index for index, line in enumerate(body) if not line.startswith("|")), len(body))
    return [line for line in body[:end] if TOTAL_LABEL not in line]


def test_render_report_writes_one_row_per_workbook_with_the_four_columns() -> None:
    tallies = [a_tally("Marvel", rows=141, auto_resolved=100), a_tally("WWII", rows=84, auto_resolved=60)]

    report = render_report(tallies, measured_on=A_DATE, resolver_version=A_VERSION)

    # The gate names these four columns by name (master plan section 10.1), so the test pins them literally.
    assert TALLY_TABLE_HEADER == "| Workbook | rows | confirmed | auto-resolved | unresolved |"
    assert TALLY_TABLE_HEADER in report
    assert "| Marvel | 141 | 0 | 100 | 41 |" in report
    assert "| WWII | 84 | 0 | 60 | 24 |" in report
    assert len(data_rows_of(report)) == len(tallies)


def test_the_totals_row_sums_every_column() -> None:
    tallies = [a_tally("Marvel", rows=141, auto_resolved=100), a_tally("WWII", rows=84, auto_resolved=60)]

    report = render_report(tallies, measured_on=A_DATE, resolver_version=A_VERSION)

    assert f"| {TOTAL_LABEL} | 225 | 0 | 160 | 65 |" in report


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        (MEASURED_ON_LABEL, f"{MEASURED_ON_LABEL}: 2026-09-20"),
        ("resolver", f"resolver: {A_VERSION}"),
    ],
)
def test_the_report_states_when_it_was_measured_and_by_what(label: str, expected: str) -> None:
    report = render_report([a_tally("Marvel")], measured_on=A_DATE, resolver_version=A_VERSION)

    assert expected in report
    assert label in report


def test_the_worst_examples_are_rendered_ascending_by_confidence_with_their_notes() -> None:
    worst = (
        an_example(9, "0.65", note="its title sits inside TMDB's"),
        an_example(2, "0.00", note="three candidates score exactly the same"),
        an_example(5, "0.50", note="found inside the parent series"),
    )

    report = render_report([a_tally("Marvel", worst=worst)], measured_on=A_DATE, resolver_version=A_VERSION)

    positions = [line for line in report.splitlines() if line.startswith("| ") and "Title " in line]
    assert [line.split(" | ")[0] for line in positions] == ["| 2", "| 5", "| 9"]
    assert "three candidates score exactly the same" in report
    assert "its title sits inside TMDB's" in report


def test_a_workbook_with_no_worst_examples_renders_no_empty_table() -> None:
    report = render_report([a_tally("Misc_Movies", worst=())], measured_on=A_DATE, resolver_version=A_VERSION)

    assert "### Misc_Movies" not in report


def test_the_confidence_rungs_are_summed_across_workbooks_highest_first() -> None:
    tallies = [
        a_tally("Marvel", rungs=((Decimal("0.95"), 80), (Decimal("0.00"), 41))),
        a_tally("WWII", rungs=((Decimal("0.95"), 20), (Decimal("0.65"), 4))),
    ]

    report = render_report(tallies, measured_on=A_DATE, resolver_version=A_VERSION)

    rungs = [line for line in report.splitlines() if line.startswith("| 0.")]
    assert rungs == ["| 0.95 | 100 |", "| 0.65 | 4 |", "| 0.00 | 41 |"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a | b", r"a \| b"),
        ("a \\ b", "a \\\\ b"),
        ("two\nlines", "two lines"),
    ],
)
def test_a_cell_can_neither_forge_a_column_nor_split_a_row(value: str, expected: str) -> None:
    worst = (WorstExample(position=1, raw_title=value, raw_unit="", confidence=Decimal("0.00"), note=""),)

    report = render_report([a_tally("Marvel", worst=worst)], measured_on=A_DATE, resolver_version=A_VERSION)

    assert expected in report
    assert len([line for line in report.splitlines() if line.startswith("| 1 |")]) == 1


def test_totals_over_the_real_library_sum_to_the_library_row_count() -> None:
    # Rows only: the counts come from the workbooks themselves, so this holds with no resolution at all.
    tallies = [a_tally(facts.stem, rows=facts.row_count, auto_resolved=0) for facts in every_workbook()]

    report = render_report(tallies, measured_on=A_DATE, resolver_version=A_VERSION)

    assert len(data_rows_of(report)) == LIBRARY_WORKBOOK_COUNT
    assert f"| {TOTAL_LABEL} | {LIBRARY_ROW_COUNT} | 0 | 0 | {LIBRARY_ROW_COUNT} |" in report


def test_the_committed_report_exists_and_has_nineteen_rows() -> None:
    """The gate item itself (master plan section 10.1): the measurement is committed, not just runnable."""
    if not COMMITTED_REPORT.exists():
        pytest.skip(f"{COMMITTED_REPORT} has not been written yet: run tv_watchlist.resolver.dry_run")
    report = COMMITTED_REPORT.read_text(encoding="utf-8")

    assert TALLY_TABLE_HEADER in report
    for column in (ROWS_COLUMN, CONFIRMED_COLUMN, AUTO_RESOLVED_COLUMN, UNRESOLVED_COLUMN):
        assert column in report
    assert f"{MEASURED_ON_LABEL}: " in report
    assert len(data_rows_of(report)) == LIBRARY_WORKBOOK_COUNT
