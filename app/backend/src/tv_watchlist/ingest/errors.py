"""What the ingest refuses to do, and why a refusal is a result rather than a crash."""

from __future__ import annotations


class IngestRefusedError(Exception):
    """The workbook was left exactly as it was, because ingesting it would have damaged its history.

    Raised for the two cases where a reconciler that carried on would silently misattribute: a Row ID cell
    holding something that is not a UUID, and a previously-ingested sheet whose rows have mostly stopped
    matching. Both mean "a human did something structural here"; neither is a fault the ingest may paper
    over (master plan section 6.3).

    Deliberately absent from `api/errors.py`'s status and message tables: no route reaches ingest in
    Phase 1, and an entry in those tables for an exception no handler can ever see would be a promise
    about a surface that does not exist. It is carried to callers on `ReconcileOutcome.refused` and to
    the UI on `category.last_ingest_error` instead. The day a route does reach ingest, it is added to
    BOTH tables in the same change, or it silently becomes a 400 (CLAUDE.md section 4.3).
    """
