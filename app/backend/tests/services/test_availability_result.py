from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from tv_watchlist.data.enums import Availability
from tv_watchlist.services.availability_result import AvailabilityResult
from tv_watchlist.services.entry_availability import EntryAvailability


def test_an_empty_page_defaults_to_no_notice() -> None:
    result = AvailabilityResult(entries={})

    assert result.entries == {}
    assert result.notice is None
    assert result.model_dump(mode="json") == {"entries": {}, "notice": None}


def test_page_entries_and_the_service_notice_keep_their_declared_types() -> None:
    entry_id = uuid.uuid4()
    item_id = uuid.uuid4()
    payload = {
        "entries": {str(entry_id): {"availability": "in_library", "jellyfin_item_id": str(item_id)}},
        "notice": "Jellyfin unreachable",
    }

    result = AvailabilityResult.model_validate(payload)

    assert result.entries == {
        entry_id: EntryAvailability(availability=Availability.IN_LIBRARY, jellyfin_item_id=item_id)
    }
    assert result.notice == "Jellyfin unreachable"
    assert result.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    ("payload", "invalid_field"),
    [
        ({}, "entries"),
        ({"entries": {"not-a-uuid": {"availability": "not_in_library"}}}, "entries"),
        ({"entries": {str(uuid.UUID(int=1)): {"availability": "unknown"}}}, "availability"),
        ({"entries": {}, "notice": 42}, "notice"),
    ],
    ids=["missing-entries", "invalid-entry-id", "invalid-nested-state", "nontext-notice"],
)
def test_invalid_page_contract_values_are_rejected(payload: dict[str, object], invalid_field: str) -> None:
    with pytest.raises(ValidationError, match=invalid_field):
        AvailabilityResult.model_validate(payload)


@pytest.mark.parametrize("field", ["entries", "notice"], ids=str)
def test_availability_result_fields_are_frozen(field: str) -> None:
    result = AvailabilityResult(entries={})

    with pytest.raises(ValidationError, match="frozen"):
        setattr(result, field, None)
