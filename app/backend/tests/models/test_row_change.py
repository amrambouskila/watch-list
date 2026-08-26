from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.constants import HEADER_ROW, MAX_REASON_LENGTH
from tv_watchlist.models.row_change import RowChange


def test_an_add_change_carries_cells_without_a_row() -> None:
    change = RowChange(kind="add", cells={"title": "Dunkirk"}, reason="listed under Sept 1939")
    assert change.kind == "add"
    assert change.row is None
    assert change.after_row is None
    assert change.cells == {"title": "Dunkirk"}
    assert change.reason == "listed under Sept 1939"


def test_a_row_number_above_the_data_region_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RowChange(kind="revise", row=HEADER_ROW, cells={"title": "Dunkirk"})


def test_an_anchor_above_the_header_row_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RowChange(kind="add", after_row=HEADER_ROW - 1, cells={"title": "Dunkirk"})


def test_a_reason_longer_than_the_cap_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at most"):
        RowChange(kind="add", cells={"title": "Dunkirk"}, reason="r" * (MAX_REASON_LENGTH + 1))


def test_an_add_change_may_not_target_an_existing_row() -> None:
    with pytest.raises(ValidationError, match="add"):
        RowChange(kind="add", row=4, cells={"title": "Dunkirk"})


def test_an_add_change_without_cells_is_rejected() -> None:
    with pytest.raises(ValidationError, match="add"):
        RowChange(kind="add", after_row=4)


def test_a_revise_change_without_a_row_is_rejected() -> None:
    with pytest.raises(ValidationError, match="revise"):
        RowChange(kind="revise", cells={"title": "Dunkirk"})


def test_a_revise_change_without_cells_is_rejected() -> None:
    with pytest.raises(ValidationError, match="revise"):
        RowChange(kind="revise", row=4)


def test_a_move_change_without_a_row_is_rejected() -> None:
    with pytest.raises(ValidationError, match="move"):
        RowChange(kind="move", after_row=9)


def test_a_move_change_without_an_anchor_is_rejected() -> None:
    with pytest.raises(ValidationError, match="move"):
        RowChange(kind="move", row=4)


def test_a_move_change_carrying_cells_is_rejected() -> None:
    with pytest.raises(ValidationError, match="move"):
        RowChange(kind="move", row=4, after_row=9, cells={"title": "Dunkirk"})


def test_a_remove_change_without_a_row_is_rejected() -> None:
    with pytest.raises(ValidationError, match="remove"):
        RowChange(kind="remove")


def test_a_remove_change_carrying_cells_is_rejected() -> None:
    with pytest.raises(ValidationError, match="remove"):
        RowChange(kind="remove", row=4, cells={"title": "Dunkirk"})


def test_cell_values_are_stripped_of_characters_excel_rejects() -> None:
    change = RowChange(kind="revise", row=4, cells={"title": "Dun\x07kirk"})
    assert change.cells == {"title": "Dunkirk"}


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "revise", "row": 4, "cells": {"title": "Dunkirk"}},
        {"kind": "move", "row": 4, "after_row": 9},
        {"kind": "remove", "row": 4},
    ],
)
def test_a_coherent_change_of_every_kind_is_accepted(change: dict[str, object]) -> None:
    assert RowChange.model_validate(change).kind == change["kind"]


def test_a_verb_outside_the_four_row_operations_is_rejected() -> None:
    with pytest.raises(ValidationError, match="reorder"):
        RowChange(kind="reorder", row=4)
