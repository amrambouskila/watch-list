"""Which sheet column carries the title, the unit, the release and the type — found by role and alias."""

from __future__ import annotations

import pytest

from library_choice import every_workbook
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.workbook.curated_columns import curated_columns, raw_type_cell
from tv_watchlist.workbook.naming import slugify
from tv_watchlist.workbook.reader import read_category
from workbook_facts import WorkbookFacts

# The one workbook whose third column is the historical event a film depicts, not a unit of that film.
EVENT_HEADER = "Event"


def _columns(*labels: str) -> list[ColumnSpec]:
    return [
        ColumnSpec(
            key=slugify(label) or f"column-{index}",
            label=label,
            index=index,
            kind="text",
            role="title" if label.lower() == "title" else "other",
            choices=[],
        )
        for index, label in enumerate(labels, start=1)
    ]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Unit", "unit"),
        ("Season / Unit", "unit"),
        ("Season / Episode / Movie", "unit"),
        ("Season / Episode Block", "unit"),
        ("Release", "release"),
        ("Release Date", "release"),
        ("Release date / period", "release"),
        ("Type", "type"),
        ("Format", "type"),
    ],
)
def test_every_spelling_the_library_uses_is_recognised(label: str, expected: str) -> None:
    found = curated_columns(_columns("Order", "Title", label))

    assert getattr(found, expected) is not None
    assert getattr(found, expected).label == label


def test_the_title_comes_from_the_role_not_from_a_label() -> None:
    columns = _columns("Order", "Title")

    assert curated_columns(columns).title is not None
    assert curated_columns(columns).title.role == "title"


def test_a_workbook_with_no_unit_column_reports_none_rather_than_guessing() -> None:
    found = curated_columns(_columns("Order", "Title", EVENT_HEADER, "Release", "Type"))

    assert found.unit is None
    assert found.release is not None
    assert found.type is not None


def test_the_cells_of_a_row_come_back_as_plain_strings() -> None:
    columns = _columns("Order", "Title", "Unit", "Release", "Type")
    row = WatchRow(row=2, cells={"title": "Max", "unit": "E1-3", "release": "2002", "type": "Film"})

    found = curated_columns(columns)

    assert found.raw_title(row) == "Max"
    assert found.raw_unit(row) == "E1-3"
    assert found.raw_release(row) == "2002"
    assert found.raw_type(row) == "Film"


def test_an_absent_column_reads_as_an_empty_string() -> None:
    found = curated_columns(_columns("Order", "Title"))
    row = WatchRow(row=2, cells={"title": "Godfather"})

    assert (found.raw_unit(row), found.raw_release(row), found.raw_type(row)) == ("", "", "")


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        ({"title": "Attack on Titan", "type": "Series"}, "Series"),
        ({"title": "Blade II", "format": "Film"}, "Film"),
        # Both headers on one sheet, the first alias empty: an empty cell states nothing, so the other
        # alias is still asked. Sorted order is what makes which one wins the same on every run.
        ({"title": "Pokemon", "type": "", "format": "TV"}, "TV"),
        # Misc_Movies' real shape: Order and Title and nothing else. Ruling 27's blank-Unit rows read
        # their kind from here, so "no Type column" must be "" rather than a guess.
        ({"title": "The Consultant"}, ""),
    ],
    ids=["type", "format", "an-empty-type-beside-a-format", "no-type-column-at-all"],
)
def test_the_type_cell_is_read_back_out_of_a_stored_rows_own_keys(cells: dict[str, str], expected: str) -> None:
    """`curated_entry.raw_cells` is keyed by the slug a header derives, so the aliases are slugified to match."""
    assert raw_type_cell(cells) == expected


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_the_stored_and_the_live_readings_of_the_type_cell_agree(facts: WorkbookFacts) -> None:
    """The stored reading is the live one's twin: whatever `raw_type` finds, `raw_type_cell` finds too.

    Asserted against all nineteen real workbooks rather than a fixture, because the two foldings this
    relies on - `normalize_header` deleting punctuation and `slugify` replacing it - only have to agree
    on the headers the library actually carries.
    """
    detail = read_category(facts.path)
    found = curated_columns(detail.columns)

    for row in detail.rows:
        assert raw_type_cell(row.cells) == found.raw_type(row)


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_every_real_workbook_yields_a_title_column(facts: WorkbookFacts) -> None:
    """The title is the one column the reconciler cannot do without; the other three are optional."""
    found = curated_columns(read_category(facts.path).columns)

    assert found.title is not None
