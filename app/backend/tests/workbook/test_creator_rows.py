from __future__ import annotations

from pathlib import Path

import pytest

from library_choice import a_name_the_library_does_not_hold
from tv_watchlist.models.category_create import CategoryCreate
from tv_watchlist.workbook.creator import create_category
from tv_watchlist.workbook.errors import UnknownColumnError
from tv_watchlist.workbook.reader import read_category

RESEARCHED_CATEGORY = a_name_the_library_does_not_hold("Wartime Chronological")
BLANK_HEADER_CATEGORY = a_name_the_library_does_not_hold("Blank Header")
RESEARCHED_COLUMNS = ["Order", "Title", "Release", "When to Watch", "Watched?"]
RESEARCHED_ROWS = [
    {"title": "Dunkirk", "release": "2017", "when-to-watch": "Sept 1939"},
    {"title": "Midway", "release": "2019", "when-to-watch": "June 1942", "watched": "Watched"},
]


def test_created_rows_fill_every_supplied_column(library: Path) -> None:
    path = create_category(
        library, CategoryCreate(name=RESEARCHED_CATEGORY, columns=RESEARCHED_COLUMNS, rows=RESEARCHED_ROWS)
    )

    detail = read_category(path)
    assert [row.cells["title"] for row in detail.rows] == ["Dunkirk", "Midway"]
    assert [row.cells["release"] for row in detail.rows] == ["2017", "2019"]
    assert [row.cells["when-to-watch"] for row in detail.rows] == ["Sept 1939", "June 1942"]
    assert [row.cells["order"] for row in detail.rows] == ["1", "2"]
    assert detail.counts.watched == 1


def test_a_row_key_the_written_headers_do_not_derive_is_refused(library: Path) -> None:
    request = CategoryCreate(name=BLANK_HEADER_CATEGORY, columns=["Order", " ", "Title"], rows=[{"column-2": "orphan"}])

    with pytest.raises(UnknownColumnError):
        create_category(library, request)
