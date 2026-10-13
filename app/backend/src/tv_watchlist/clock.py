"""The one wall clock. Injected as `clock=utcnow` so a test can hand in a fixed one."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware now, matching every `DateTime(timezone=True)` column in the schema."""
    return datetime.now(UTC)
