from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.constants import MAX_PROPOSAL_SOURCES
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.models.proposal_create import ProposalCreate
from tv_watchlist.models.proposal_edit import ProposalEdit

READ_MTIME = 1_700_000_000.5


def test_a_create_body_parses_into_the_create_arm() -> None:
    proposal = Proposal.model_validate(
        {
            "id": "p-1",
            "summary": "91 wartime films in chronological order",
            "body": {
                "kind": "create",
                "category": {"name": "Wartime", "columns": ["Title"], "rows": [{"title": "Dunkirk"}]},
            },
        }
    )
    assert isinstance(proposal.body, ProposalCreate)
    assert proposal.body.category.rows == [{"title": "Dunkirk"}]


def test_a_body_with_an_unknown_kind_fails_on_the_tag_alone() -> None:
    with pytest.raises(ValidationError) as raised:
        Proposal.model_validate({"id": "p-1", "summary": "reshuffle", "body": {"kind": "reorder"}})
    errors = raised.value.errors()
    assert [error["type"] for error in errors] == ["union_tag_invalid"]
    assert errors[0]["loc"] == ("body",)


def test_more_sources_than_the_cap_are_rejected() -> None:
    too_many = [f"https://example.test/{index}" for index in range(MAX_PROPOSAL_SOURCES + 1)]
    with pytest.raises(ValidationError, match="at most"):
        Proposal.model_validate(
            {
                "id": "p-1",
                "summary": "over-cited",
                "sources": too_many,
                "body": {
                    "kind": "edit",
                    "category_id": "a-category",
                    "read_mtime": READ_MTIME,
                    "changes": [],
                },
            }
        )


def test_an_edit_body_parses_into_the_edit_arm() -> None:
    proposal = Proposal.model_validate(
        {
            "id": "p-2",
            "summary": "drop a duplicate",
            "body": {
                "kind": "edit",
                "category_id": "a-category",
                "read_mtime": READ_MTIME,
                "changes": [{"kind": "remove", "row": 7, "reason": "duplicate of row 4"}],
            },
        }
    )
    assert isinstance(proposal.body, ProposalEdit)
    assert proposal.body.changes[0].reason == "duplicate of row 4"
