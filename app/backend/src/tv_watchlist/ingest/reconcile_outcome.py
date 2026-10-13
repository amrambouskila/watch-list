"""What one reconciliation pass did to one workbook, in the counts a log record and a caller both need."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    """One pass over one category.

    A pass that changed nothing still reports its zeros: "no output" is indistinguishable from "did not
    run" (CLAUDE.md section 9.2). `refused` carries the reason the workbook was left alone, and when it is
    set every count is zero and `workbook_written` is `False` - the pass rolled back.
    """

    slug: str
    skipped: bool = False
    matched: int = 0
    adopted: int = 0
    minted: int = 0
    reminted: int = 0
    removed: int = 0
    reresolved: int = 0
    # Titles whose cached provider payload had reached TMDB's six-month cap and was re-ingested. Not part
    # of `reresolved`, because no search was spent and no row changed which work it means.
    refreshed: int = 0
    workbook_written: bool = False
    refused: str | None = None
