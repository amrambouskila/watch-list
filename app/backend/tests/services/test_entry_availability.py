from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from tv_watchlist.data.enums import Availability
from tv_watchlist.services.entry_availability import EntryAvailability


@pytest.mark.parametrize("state", tuple(Availability), ids=str)
def test_an_entry_state_is_typed_and_defaults_to_no_title_level_id(state: Availability) -> None:
    result = EntryAvailability.model_validate({"availability": state.value})

    assert result.availability is state
    assert result.jellyfin_item_id is None
    assert result.model_dump(mode="json") == {"availability": state.value, "jellyfin_item_id": None}


def test_a_title_level_id_is_parsed_as_a_uuid() -> None:
    item_id = uuid.uuid4()

    result = EntryAvailability.model_validate({"availability": "in_library", "jellyfin_item_id": str(item_id)})

    assert result.jellyfin_item_id == item_id
    assert result.model_dump(mode="json") == {"availability": "in_library", "jellyfin_item_id": str(item_id)}


@pytest.mark.parametrize(
    ("payload", "invalid_field"),
    [
        ({}, "availability"),
        ({"availability": "unknown"}, "availability"),
        ({"availability": "in_library", "jellyfin_item_id": "not-a-uuid"}, "jellyfin_item_id"),
    ],
    ids=["missing-state", "unknown-state", "invalid-title-id"],
)
def test_invalid_entry_contract_values_are_rejected(payload: dict[str, str], invalid_field: str) -> None:
    with pytest.raises(ValidationError, match=invalid_field):
        EntryAvailability.model_validate(payload)


@pytest.mark.parametrize("field", ["availability", "jellyfin_item_id"], ids=str)
def test_entry_availability_fields_are_frozen(field: str) -> None:
    result = EntryAvailability(availability=Availability.NOT_IN_LIBRARY)

    with pytest.raises(ValidationError, match="frozen"):
        setattr(result, field, None)
