from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.constants import MAX_CELL_LENGTH, MAX_NEW_CATEGORY_ROWS
from tv_watchlist.models.category_create import CategoryCreate


def test_rows_are_kept_when_every_key_matches_a_column() -> None:
    category = CategoryCreate(
        name="Wartime",
        columns=["Order", "Title", "When to Watch"],
        rows=[{"order": "1", "title": "Dunkirk", "when-to-watch": "First"}],
    )
    assert category.rows == [{"order": "1", "title": "Dunkirk", "when-to-watch": "First"}]


@pytest.mark.parametrize("key", ["runtime", "When to Watch", "Title"])
def test_a_row_key_that_no_column_derives_is_rejected_by_name(key: str) -> None:
    with pytest.raises(ValidationError, match=key):
        CategoryCreate(name="Wartime", columns=["Order", "Title", "When to Watch"], rows=[{key: "Dunkirk"}])


def test_titles_and_rows_together_are_rejected_as_ambiguous() -> None:
    with pytest.raises(ValidationError, match="titles"):
        CategoryCreate(name="Wartime", columns=["Order", "Title"], titles=["Dunkirk"], rows=[{"title": "Dunkirk"}])


def test_more_rows_than_the_cap_are_rejected() -> None:
    too_many = [{"title": f"Film {index}"} for index in range(MAX_NEW_CATEGORY_ROWS + 1)]
    with pytest.raises(ValidationError, match="at most"):
        CategoryCreate(name="Wartime", columns=["Order", "Title"], rows=too_many)


def test_row_values_are_stripped_of_characters_excel_rejects() -> None:
    category = CategoryCreate(name="Wartime", columns=["Title"], rows=[{"title": "Dun\x07kirk"}])
    assert category.rows == [{"title": "Dunkirk"}]


def test_row_values_are_clipped_to_a_cells_capacity() -> None:
    category = CategoryCreate(name="Wartime", columns=["Notes"], rows=[{"notes": "n" * (MAX_CELL_LENGTH + 10)}])
    assert len(category.rows[0]["notes"]) == MAX_CELL_LENGTH


@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        (["Order", "Title", "When to Watch"], ["order", "title", "when-to-watch"]),
        (["Title", "Title"], ["title", "title-2"]),
        (["Title", "!!!"], ["title", "column-2"]),
    ],
)
def test_column_keys_follow_the_sheet_readers_vocabulary(columns: list[str], expected: list[str]) -> None:
    assert CategoryCreate(name="Wartime", columns=columns).column_keys() == expected
