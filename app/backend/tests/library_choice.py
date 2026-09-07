"""Choosing a library workbook by a stable property instead of by the name its owner gave it."""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Final

from tv_watchlist.config import Settings
from tv_watchlist.constants import DEFAULT_NEW_CATEGORY_COLUMNS, EXCEL_LOCK_PREFIX, WORKBOOK_SUFFIX
from tv_watchlist.workbook.naming import workbook_filename
from workbook_facts import WorkbookFacts, read_facts

# Honours TV_LIBRARY_DIR, so the whole suite can be pointed at a copy of the library.
LIBRARY_DIR: Final[Path] = Settings().library_dir

Property = Callable[[WorkbookFacts], bool]

# A batch that removes one row, reseats another and appends two needs this much sheet under it.
ROWS_ENOUGH_TO_REORDER: Final[int] = 8
# The header the app itself writes over an order column; a hand-built sheet may use a symbol instead.
ORDER_HEADER_WORD: Final[str] = DEFAULT_NEW_CATEGORY_COLUMNS[0]


def library_workbooks() -> list[Path]:
    """The real workbooks this app is built for."""
    return sorted(
        path for path in LIBRARY_DIR.glob(f"*{WORKBOOK_SUFFIX}") if not path.name.startswith(EXCEL_LOCK_PREFIX)
    )


@cache
def every_workbook() -> tuple[WorkbookFacts, ...]:
    """Facts for every workbook in the library, read once for the whole session."""
    return tuple(read_facts(path) for path in library_workbooks())


def a_name_the_library_does_not_hold(preferred: str) -> str:
    """A display name a test may create or rename onto, refused loudly if the owner already uses it."""
    taken = {facts.stem.casefold() for facts in every_workbook()}
    if Path(workbook_filename(preferred)).stem.casefold() in taken:
        raise AssertionError(f"the library already holds a category named {preferred}; pick another for the test")
    return preferred


def the_category_a_new_name_could_shadow() -> WorkbookFacts:
    """A category the library also answers for under a filename it does not yet hold."""
    taken = {facts.file_name.casefold() for facts in every_workbook()}
    return _shallowest(
        "addressable under a filename the library does not hold",
        lambda facts: workbook_filename(facts.shadowing_name).casefold() not in taken,
    )


def _shallowest(described_as: str, matching: Property) -> WorkbookFacts:
    """The smallest workbook with the wanted shape, so a test that rewrites it stays quick."""
    found = sorted(
        (facts for facts in every_workbook() if matching(facts)),
        key=lambda facts: (facts.row_count, facts.column_count, facts.file_name),
    )
    if not found:
        raise AssertionError(f"the library holds no workbook that is {described_as}")
    return found[0]


def _the_only(described_as: str, matching: Property) -> WorkbookFacts:
    """The one workbook with a shape no other workbook in the library shares."""
    found = [facts for facts in every_workbook() if matching(facts)]
    if len(found) != 1:
        raise AssertionError(f"expected exactly one workbook {described_as}, found {len(found)}")
    return found[0]


def _is_an_ordinary_editable_category(facts: WorkbookFacts) -> bool:
    return (
        facts.is_unmarked
        and bool(facts.free_text_keys)
        and facts.ranges_all_end_together
        and facts.row_count >= ROWS_ENOUGH_TO_REORDER
        and bool(facts.rows_a_deletion_at_the_top_would_retitle)
    )


def a_category() -> WorkbookFacts:
    """The default subject: nothing marked yet, a free-text column, depth to reorder, and a row a
    deletion above would retitle."""
    return _shallowest("an unmarked, reorderable category", _is_an_ordinary_editable_category)


def ordinary_editable_categories(matching: Property) -> list[WorkbookFacts]:
    """
    Every ordinary editable category that also matches `matching`, shallowest first.

    For a test file needing more of its subject than `a_category` promises, and needing any second
    subject narrowed the same way - drawing the second from `another_category` instead can hand back
    the very workbook the extra property just steered the first one away from.
    """
    return sorted(
        (facts for facts in every_workbook() if _is_an_ordinary_editable_category(facts) and matching(facts)),
        key=lambda facts: (facts.row_count, facts.column_count, facts.file_name),
    )


def another_category() -> WorkbookFacts:
    """A second category, distinct from the first and stamped at a different time."""
    first = a_category()
    return _shallowest(
        "a second unmarked, reorderable category stamped at its own time",
        lambda facts: (
            _is_an_ordinary_editable_category(facts) and facts.path != first.path and facts.mtime != first.mtime
        ),
    )


def a_category_with_at_least(rows: int) -> WorkbookFacts:
    """A category deep enough for a test that reaches a specific row number."""
    return _shallowest(f"a category of at least {rows} rows", lambda facts: facts.row_count >= rows)


def a_category_part_way_through() -> WorkbookFacts:
    """A category holding both a watched and an unwatched row, so both markers are on show."""
    return _shallowest(
        "a category holding both a watched and an unwatched row",
        lambda facts: facts.watched_row_count > 0 and facts.unwatched_row_count > 0,
    )


def a_category_carrying_reference_sheets(*, at_least: int) -> WorkbookFacts:
    """A category whose workbook holds sheets beside the watch order itself."""
    return _shallowest(
        f"a category carrying at least {at_least} reference sheets",
        lambda facts: facts.reference_sheet_count >= at_least,
    )


def a_category_whose_order_column_holds_numbers() -> WorkbookFacts:
    """A category whose order cells are numbers, not the text that looks like them."""
    return _shallowest("a category numbering its rows numerically", lambda facts: facts.order_holds_numbers)


def the_category_with_a_stale_formatting_range() -> WorkbookFacts:
    """The one category whose dropdown and highlight stop short of the rows the table covers."""
    return _the_only("with a construct stopping short of its grid", lambda facts: not facts.ranges_all_end_together)


def the_category_whose_order_column_is_not_headed_order() -> WorkbookFacts:
    """The one category numbering its rows under a symbol rather than the word."""
    return _the_only(
        f"headed by something other than the word {ORDER_HEADER_WORD}",
        lambda facts: facts.order_label != ORDER_HEADER_WORD,
    )


def the_category_with_dropdowns_beyond_the_watch_column() -> WorkbookFacts:
    """The one category whose owner built dropdowns of their own beside the watch status."""
    return _the_only("carrying dropdowns of its own", lambda facts: bool(facts.dropdown_keys_beyond_the_watch_column))
