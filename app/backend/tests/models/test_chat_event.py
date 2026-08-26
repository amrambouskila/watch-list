from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.models.chat_event import ChatEvent


def test_a_text_frame_carries_only_its_text() -> None:
    event = ChatEvent(type="text", text="Searching for chronological wartime film lists")
    assert event.type == "text"
    assert event.text == "Searching for chronological wartime film lists"


def test_a_tool_frame_carries_the_tool_name_its_detail_and_its_state() -> None:
    event = ChatEvent(type="tool", name="fetch_url", detail="reddit.com/r/movies", state="escalated")
    assert (event.name, event.detail, event.state) == ("fetch_url", "reddit.com/r/movies", "escalated")


def test_a_proposal_frame_nests_a_validated_proposal() -> None:
    event = ChatEvent.model_validate(
        {
            "type": "proposal",
            "proposal": {
                "id": "p-1",
                "summary": "91 wartime films",
                "body": {
                    "kind": "create",
                    "category": {"name": "Wartime", "columns": ["Title"], "rows": [{"title": "Fury"}]},
                },
            },
        }
    )
    assert event.proposal is not None
    assert event.proposal.summary == "91 wartime films"


def test_an_error_frame_carries_a_code_and_a_message() -> None:
    event = ChatEvent(type="error", code="WorkbookLocked", message="Close it in Excel and approve again")
    assert (event.code, event.message) == ("WorkbookLocked", "Close it in Excel and approve again")


def test_a_done_frame_reports_turns_and_total_cost_never_cost_usd() -> None:
    event = ChatEvent(type="done", turns=7, total_cost_usd=0.14)
    assert event.turns == 7
    assert event.total_cost_usd == pytest.approx(0.14)
    assert not hasattr(event, "cost_usd")


def test_an_sse_line_omits_every_field_the_frame_does_not_use() -> None:
    event = ChatEvent(type="tool", name="fetch_url", detail="reddit.com/r/movies", state="escalated")
    assert event.model_dump(exclude_none=True) == {
        "type": "tool",
        "name": "fetch_url",
        "detail": "reddit.com/r/movies",
        "state": "escalated",
    }


def test_a_frame_type_outside_the_streams_vocabulary_is_rejected() -> None:
    with pytest.raises(ValidationError, match="thinking"):
        ChatEvent(type="thinking")
