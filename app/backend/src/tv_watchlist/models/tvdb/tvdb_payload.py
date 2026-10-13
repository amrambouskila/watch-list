"""The shape every recorded TheTVDB response shares."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TvdbPayload(BaseModel):
    """Frozen, and silently dropping fields TheTVDB adds: a provider may grow a key without breaking an ingest."""

    # `extra="ignore"` is the untrusted-boundary rule (CLAUDE.md section 10.3, B10): nothing this client did
    # not ask for is carried forward, so no upstream field can reach SQL or a template by accident.
    model_config = ConfigDict(extra="ignore", frozen=True)
