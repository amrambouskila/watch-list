from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from ts_types import ts_fields
from tv_watchlist.data.enums import Availability
from tv_watchlist.models.playback_item_read import PlaybackItemRead


def test_playback_item_has_the_exact_typescript_contract_and_is_frozen() -> None:
    item = PlaybackItemRead(
        id=uuid.uuid4(),
        entry_id=uuid.uuid4(),
        episode_id=None,
        movie_title_id=uuid.uuid4(),
        position_in_entry=1,
        absolute_position=7,
        availability=Availability.NOT_IN_LIBRARY,
        jellyfin_item_id=None,
        order_type=None,
        order_label="",
        covers_range=False,
    )
    assert list(PlaybackItemRead.model_fields) == ts_fields("PlaybackItemRead")
    assert PlaybackItemRead.model_config["from_attributes"] is True
    with pytest.raises(ValidationError, match="frozen"):
        item.absolute_position = 2


@pytest.mark.parametrize("field", ["position_in_entry", "absolute_position"])
def test_queue_positions_are_positive_at_the_boundary(field: str) -> None:
    with pytest.raises(ValidationError):
        PlaybackItemRead.model_validate(
            {
                "id": uuid.uuid4(),
                "entry_id": uuid.uuid4(),
                "episode_id": None,
                "movie_title_id": uuid.uuid4(),
                "position_in_entry": 1,
                "absolute_position": 1,
                "availability": "not_in_library",
                "jellyfin_item_id": None,
                "order_type": None,
                "order_label": "",
                "covers_range": False,
                field: 0,
            }
        )
