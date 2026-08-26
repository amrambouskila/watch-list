"""The terminal tool: validated model output becomes a pending proposal, and nothing else."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import uuid4

from claude_agent_sdk import SdkMcpTool, tool
from pydantic import ValidationError

from tv_watchlist.agent.constants import PROPOSE_TOOL, QUALIFIED_GET_CATEGORY_TOOL
from tv_watchlist.agent.handler_guard import log_handler_failures
from tv_watchlist.agent.read_log import ReadLog
from tv_watchlist.agent.tool_result import ToolResult, text_result
from tv_watchlist.models.proposal import Proposal

ProposalRecorder = Callable[[Proposal], Awaitable[None]]

_ID_FIELD: Final[str] = "id"
_BODY_FIELD: Final[str] = "body"
_KIND_FIELD: Final[str] = "kind"
_CATEGORY_ID_FIELD: Final[str] = "category_id"
_READ_MTIME_FIELD: Final[str] = "read_mtime"
_EDIT_KIND: Final[str] = "edit"
_PROPERTIES_KEY: Final[str] = "properties"
_REQUIRED_KEY: Final[str] = "required"
# The backend mints both from what it knows. A model-chosen id would collide with a real proposal, and
# a model-chosen freshness stamp would defeat the very guard it is compared against.
_UNREAD_CATEGORY: Final[str] = (
    "Call {tool} for {category_id} before proposing an edit to it: row numbers only mean something "
    "against the grid you actually read."
)
_DESCRIPTION = (
    "Offer a change for the user to review. This is the only way anything reaches a workbook, and "
    "nothing is written until the user approves the diff. Give a create body for a brand-new "
    "category or an edit body of row changes for an existing one, plus every source you consulted. "
    "Read a category with get_category before proposing an edit to it; its rows are what the row "
    "numbers in your changes are resolved against."
)


def _drop_field(node: dict[str, object], field: str) -> None:
    """Drop one field from one schema object, its required list included."""
    properties = node.get(_PROPERTIES_KEY)
    if isinstance(properties, dict):
        properties.pop(field, None)
    required = node.get(_REQUIRED_KEY)
    if isinstance(required, list):
        node[_REQUIRED_KEY] = [name for name in required if name != field]


def _drop_field_everywhere(node: object, field: str) -> None:
    """Drop one field from every object in a schema tree, however deeply the arm carrying it is nested."""
    if isinstance(node, list):
        for item in node:
            _drop_field_everywhere(item, field)
        return
    if not isinstance(node, dict):
        return
    _drop_field(node, field)
    for value in node.values():
        _drop_field_everywhere(value, field)


def _hide_minted_fields(schema: dict[str, object]) -> None:
    """Hide each minted field where it actually lives: the id on the proposal itself, the stamp on a nested arm."""
    _drop_field(schema, _ID_FIELD)
    _drop_field_everywhere(schema, _READ_MTIME_FIELD)


def _arguments_schema() -> dict[str, object]:
    """The proposal schema minus what the backend mints, so the model cannot choose either field."""
    schema = Proposal.model_json_schema()
    _hide_minted_fields(schema)
    return schema


def build_propose_tool(record: ProposalRecorder, read_log: ReadLog) -> SdkMcpTool[dict[str, object]]:
    """Bind the propose tool to the session that will hold the pending proposal and to what it has read."""

    async def propose(args: dict[str, object]) -> ToolResult:
        payload = {**args, _ID_FIELD: uuid4().hex}
        body = payload.get(_BODY_FIELD)
        if isinstance(body, dict) and body.get(_KIND_FIELD) == _EDIT_KIND:
            category_id = str(body.get(_CATEGORY_ID_FIELD, ""))
            read_mtime = read_log.mtime_of(category_id)
            if read_mtime is None:
                message = _UNREAD_CATEGORY.format(tool=QUALIFIED_GET_CATEGORY_TOOL, category_id=category_id)
                return text_result(message, is_error=True)
            payload[_BODY_FIELD] = {**body, _READ_MTIME_FIELD: read_mtime}
        try:
            proposal = Proposal.model_validate(payload)
        except ValidationError as error:
            return text_result(str(error), is_error=True)
        await record(proposal)
        return text_result(json.dumps({"proposal_id": proposal.id, "summary": proposal.summary}))

    return tool(PROPOSE_TOOL, _DESCRIPTION, _arguments_schema())(log_handler_failures(PROPOSE_TOOL, propose))
