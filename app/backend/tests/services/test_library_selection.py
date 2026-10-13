from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError

import pytest

from tv_watchlist.services.library_selection import LibrarySelection


def test_an_empty_selection_has_no_candidate_or_ambiguity() -> None:
    result = LibrarySelection.from_rows([])

    assert result == LibrarySelection()
    assert result.item_id is None
    assert result.series_ids == ()
    assert result.ambiguous is False
    assert result.pick_dangling is False


def test_a_populated_selection_keeps_its_typed_id_and_immutable_series_scope() -> None:
    item_id = uuid.uuid4()
    series_ids = (uuid.uuid4().hex, uuid.uuid4().hex)

    result = LibrarySelection(item_id=item_id, series_ids=series_ids, ambiguous=True, pick_dangling=True)

    assert result.item_id == item_id
    assert result.series_ids == series_ids
    assert isinstance(result.series_ids, tuple)
    assert result.ambiguous is True
    assert result.pick_dangling is True


@pytest.mark.parametrize("field", ["item_id", "series_ids", "ambiguous", "pick_dangling"], ids=str)
def test_library_selection_fields_are_frozen(field: str) -> None:
    result = LibrarySelection()

    with pytest.raises(FrozenInstanceError):
        setattr(result, field, None)
