"""The terminal tool: the only route from model output towards a workbook."""

from __future__ import annotations

import json

from claude_agent_sdk import SdkMcpTool

from tv_watchlist.agent.constants import PROPOSE_TOOL, QUALIFIED_GET_CATEGORY_TOOL
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.tools.propose import _hide_minted_fields, build_propose_tool
from tv_watchlist.models.proposal import Proposal

COLUMNS = ["Order", "Title", "When to Watch", "Watched?"]
CATEGORY_ID = "a-category"
OTHER_CATEGORY_ID = "a-different-category"
READ_MTIME = 1_700_000_000.5
OTHER_READ_MTIME = 1_700_000_900.25
CREATE_BODY = {
    "kind": "create",
    "category": {
        "name": "Wartime Chronological",
        "columns": COLUMNS,
        "rows": [{"order": "1", "title": "Dunkirk", "when-to-watch": "May 1940"}],
    },
}
EDIT_BODY = {
    "kind": "edit",
    "category_id": CATEGORY_ID,
    "changes": [{"kind": "add", "after_row": 4, "cells": {"title": "A researched entry"}, "reason": "missing"}],
}
HERO_BODY = {
    "kind": "hero",
    "category_id": CATEGORY_ID,
    "candidates": [
        {
            "url": "https://upload.wikimedia.org/wikipedia/commons/6/6c/Series_Logo.png",
            "source_file": "Series Logo.png",
            "licence": "Public domain",
            "page": "https://commons.wikimedia.org/wiki/File:Series_Logo.png",
            "description": "The original logotype on transparency.",
        }
    ],
}


class Recorder:
    """Stands in for the chat session that holds the pending proposal."""

    def __init__(self) -> None:
        self.recorded: list[Proposal] = []

    async def __call__(self, proposal: Proposal) -> None:
        self.recorded.append(proposal)


def a_nested_schema() -> dict[str, object]:
    """A schema whose nested object carries both minted names, which the real proposal tree does not."""
    return {
        "properties": {
            "id": {"type": "string"},
            "body": {
                "properties": {
                    "id": {"type": "string"},
                    "read_mtime": {"type": "number"},
                    "category_id": {"type": "string"},
                },
                "required": ["id", "read_mtime", "category_id"],
            },
        },
        "required": ["id", "body"],
    }


def a_read_log() -> ReadLog:
    """A session that has already read the category the edit bodies here name."""
    read_log = ReadLog()
    read_log.record(CATEGORY_ID, READ_MTIME)
    return read_log


async def test_the_tool_is_named_for_the_spec() -> None:
    assert isinstance(build_propose_tool(Recorder(), ReadLog()), SdkMcpTool)
    assert build_propose_tool(Recorder(), ReadLog()).name == PROPOSE_TOOL


async def test_a_valid_create_proposal_is_recorded_and_its_id_returned() -> None:
    recorder = Recorder()

    result = await build_propose_tool(recorder, ReadLog()).handler(
        {"summary": "91 wartime films in event order", "sources": ["https://example.com/list"], "body": CREATE_BODY}
    )

    assert result["is_error"] is False
    payload = json.loads(result["content"][0]["text"])
    assert len(recorder.recorded) == 1
    assert payload["proposal_id"] == recorder.recorded[0].id
    assert payload["summary"] == "91 wartime films in event order"
    assert recorder.recorded[0].sources == ["https://example.com/list"]


async def test_the_proposal_id_is_minted_here_not_taken_from_the_model() -> None:
    recorder = Recorder()

    await build_propose_tool(recorder, ReadLog()).handler(
        {"id": "chosen-by-claude", "summary": "s", "body": CREATE_BODY}
    )

    assert recorder.recorded[0].id != "chosen-by-claude"


async def test_the_advertised_schema_offers_neither_field_the_backend_mints_itself() -> None:
    schema = build_propose_tool(Recorder(), ReadLog()).input_schema

    advertised = json.dumps(schema)
    # Both arms that name a category are genuinely in the advertised tree, so a read_mtime nested in
    # either of them would have shown up here.
    assert "category_id" in advertised
    assert "candidates" in advertised
    assert "read_mtime" not in advertised
    assert "id" not in schema["properties"]
    assert schema["required"] == ["summary", "body"]


async def test_a_row_key_outside_the_declared_columns_is_rejected_before_anything_is_recorded() -> None:
    recorder = Recorder()
    body = json.loads(json.dumps(CREATE_BODY))
    body["category"]["rows"] = [{"title": "Dunkirk", "director": "Nolan"}]

    result = await build_propose_tool(recorder, ReadLog()).handler({"summary": "s", "body": body})

    assert result["is_error"] is True
    assert "director" in result["content"][0]["text"]
    assert recorder.recorded == []


async def test_a_body_missing_its_summary_is_rejected() -> None:
    recorder = Recorder()

    result = await build_propose_tool(recorder, ReadLog()).handler({"body": CREATE_BODY})

    assert result["is_error"] is True
    assert recorder.recorded == []


async def test_an_edit_proposal_carrying_row_changes_is_accepted() -> None:
    recorder = Recorder()

    result = await build_propose_tool(recorder, a_read_log()).handler({"summary": "add Andor", "body": EDIT_BODY})

    assert result["is_error"] is False
    assert recorder.recorded[0].body.kind == "edit"


async def test_an_edit_is_stamped_with_the_mtime_the_session_read_that_category_at() -> None:
    recorder = Recorder()

    await build_propose_tool(recorder, a_read_log()).handler({"summary": "add Andor", "body": EDIT_BODY})

    assert recorder.recorded[0].body.read_mtime == READ_MTIME


async def test_an_edit_is_stamped_for_its_own_category_not_whichever_was_read_most_recently() -> None:
    recorder = Recorder()
    read_log = a_read_log()
    read_log.record(OTHER_CATEGORY_ID, OTHER_READ_MTIME)

    await build_propose_tool(recorder, read_log).handler({"summary": "add Andor", "body": EDIT_BODY})

    assert recorder.recorded[0].body.read_mtime == READ_MTIME


async def test_a_read_mtime_the_model_supplied_itself_never_survives_the_recorded_one() -> None:
    recorder = Recorder()
    body = {**EDIT_BODY, "read_mtime": READ_MTIME + 500.0}

    await build_propose_tool(recorder, a_read_log()).handler({"summary": "add Andor", "body": body})

    assert recorder.recorded[0].body.read_mtime == READ_MTIME


async def test_an_edit_to_a_category_this_session_never_read_is_refused_rather_than_stamped() -> None:
    recorder = Recorder()

    result = await build_propose_tool(recorder, ReadLog()).handler({"summary": "add Andor", "body": EDIT_BODY})

    assert result["is_error"] is True
    assert QUALIFIED_GET_CATEGORY_TOOL in result["content"][0]["text"]
    assert CATEGORY_ID in result["content"][0]["text"]
    assert recorder.recorded == []


async def test_a_create_proposal_needs_no_prior_read_because_it_names_no_existing_rows() -> None:
    recorder = Recorder()

    result = await build_propose_tool(recorder, ReadLog()).handler({"summary": "a new sheet", "body": CREATE_BODY})

    assert result["is_error"] is False


async def test_a_hero_proposal_needs_no_prior_read_because_it_touches_no_rows() -> None:
    recorder = Recorder()

    result = await build_propose_tool(recorder, ReadLog()).handler({"summary": "artwork", "body": HERO_BODY})

    assert result["is_error"] is False
    assert recorder.recorded[0].body.kind == "hero"


async def test_a_hero_proposal_is_never_stamped_with_a_freshness_the_write_would_not_use() -> None:
    recorder = Recorder()

    await build_propose_tool(recorder, a_read_log()).handler({"summary": "artwork", "body": HERO_BODY})

    assert not hasattr(recorder.recorded[0].body, "read_mtime")


async def test_an_incoherent_row_change_is_rejected_rather_than_stored() -> None:
    recorder = Recorder()
    body = {"kind": "edit", "category_id": CATEGORY_ID, "changes": [{"kind": "remove", "row": 4, "cells": {"a": "b"}}]}

    result = await build_propose_tool(recorder, a_read_log()).handler({"summary": "drop it", "body": body})

    assert result["is_error"] is True
    assert recorder.recorded == []


def test_an_id_on_a_nested_object_stays_advertised_because_only_the_proposal_id_is_minted() -> None:
    schema = a_nested_schema()

    _hide_minted_fields(schema)

    assert "id" in schema["properties"]["body"]["properties"]
    assert schema["properties"]["body"]["required"] == ["id", "category_id"]


def test_the_top_level_id_is_hidden_because_the_backend_mints_that_one() -> None:
    schema = a_nested_schema()

    _hide_minted_fields(schema)

    assert "id" not in schema["properties"]
    assert schema["required"] == ["body"]


def test_a_read_mtime_is_hidden_however_deeply_the_arm_carrying_it_is_nested() -> None:
    schema = a_nested_schema()

    _hide_minted_fields(schema)

    assert "read_mtime" not in schema["properties"]["body"]["properties"]
