"""Translate domain failures into HTTP responses the UI can act on."""

from __future__ import annotations

from typing import Final

from claude_agent_sdk import CLINotFoundError
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from openpyxl.utils.exceptions import IllegalCharacterError

from tv_watchlist.agent.errors import (
    AgentError,
    HeroChoiceRequiredError,
    NoHeroCandidatesError,
    UnknownHeroCandidateError,
    UnknownProposalError,
    UnknownSessionError,
)
from tv_watchlist.workbook.errors import (
    CategoryNotFoundError,
    DuplicateCategoryError,
    InvalidChoiceError,
    MissingWatchColumnError,
    RowNotFoundError,
    StaleWorkbookError,
    UnknownColumnError,
    UnreadableWorkbookError,
    WorkbookError,
    WorkbookLockedError,
)

_STATUS_BY_ERROR: dict[type[Exception], int] = {
    CategoryNotFoundError: status.HTTP_404_NOT_FOUND,
    RowNotFoundError: status.HTTP_404_NOT_FOUND,
    WorkbookLockedError: status.HTTP_423_LOCKED,
    StaleWorkbookError: status.HTTP_409_CONFLICT,
    DuplicateCategoryError: status.HTTP_409_CONFLICT,
    UnknownColumnError: status.HTTP_400_BAD_REQUEST,
    InvalidChoiceError: status.HTTP_400_BAD_REQUEST,
    MissingWatchColumnError: status.HTTP_400_BAD_REQUEST,
    UnreadableWorkbookError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CLINotFoundError: status.HTTP_503_SERVICE_UNAVAILABLE,
    UnknownSessionError: status.HTTP_404_NOT_FOUND,
    UnknownProposalError: status.HTTP_404_NOT_FOUND,
}

_MESSAGE_BY_ERROR: dict[type[Exception], str] = {
    CategoryNotFoundError: "No workbook matches '{detail}'.",
    RowNotFoundError: "Row {detail} is no longer in this sheet.",
    WorkbookLockedError: "{detail} is open in Excel. Close it and try again.",
    StaleWorkbookError: "{detail} changed on disk. Reloading so your edit does not overwrite it.",
    DuplicateCategoryError: "{detail} already exists.",
    UnknownColumnError: "This sheet has no column '{detail}'.",
    InvalidChoiceError: "That value is not one of the sheet's options ({detail}).",
    MissingWatchColumnError: "This sheet has no Watched? column yet.",
    UnreadableWorkbookError: "{detail} could not be opened as a workbook.",
    CLINotFoundError: "Claude Code is not installed, or `claude` is not on this machine's PATH.",
    UnknownSessionError: "Chat session '{detail}' has ended. Start a new one.",
    UnknownProposalError: "Proposal '{detail}' is no longer pending. Ask Claude to propose it again.",
    HeroChoiceRequiredError: "Artwork is chosen, not approved. Pick one of this proposal's candidates instead.",
    NoHeroCandidatesError: "Proposal '{detail}' offers a change to approve, not artwork to choose.",
    UnknownHeroCandidateError: "This proposal has no candidate {detail}.",
}

_HANDLED_BASES: Final[tuple[type[Exception], ...]] = (WorkbookError, AgentError, CLINotFoundError)


def payload_for(error: Exception) -> dict[str, str]:
    """The `{error, message, detail}` envelope every refusal returns, whichever status carries it."""
    detail = str(error)
    template = _MESSAGE_BY_ERROR.get(type(error), "{detail}")
    return {"error": type(error).__name__, "message": template.format(detail=detail), "detail": detail}


def register(app: FastAPI) -> None:
    """Attach the domain error handlers to the application."""

    @app.exception_handler(IllegalCharacterError)
    async def _handle_illegal(_: Request, error: IllegalCharacterError) -> JSONResponse:
        """openpyxl raises this from bare Exception, so it needs its own handler to avoid a 500."""
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "IllegalCharacterError",
                "message": "That text contains characters Excel cannot store in a cell.",
                "detail": str(error),
            },
        )

    async def _handle(_: Request, error: Exception) -> JSONResponse:
        code = _STATUS_BY_ERROR.get(type(error), status.HTTP_400_BAD_REQUEST)
        return JSONResponse(status_code=code, content=payload_for(error))

    for base in _HANDLED_BASES:
        app.add_exception_handler(base, _handle)
