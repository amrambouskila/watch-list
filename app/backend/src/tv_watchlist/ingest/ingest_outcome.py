"""What one ingest pass did, in the four counts a log record and a caller both need."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from tv_watchlist.clients.transport import CacheOutcome

# Loudest wins when two passes are merged. `failed` outranks `fresh` because a series whose title was
# rewritten and whose eleventh season could not be read has not succeeded; `cached` is the quietest,
# because nothing was even attempted.
_LOUDNESS: Final[tuple[CacheOutcome, ...]] = ("cached", "not-modified", "throttled", "fresh", "failed")


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """Rows inserted, updated, left alone and skipped, plus what the provider leg of the pass amounted to.

    `unchanged` counts rows the ingest looked at and deliberately did not write; `skipped` counts
    resources it never looked at, because a backoff had not run out or the upstream has no such thing.
    A pass that changed nothing is `IngestOutcome()`, and that is a result worth logging rather than
    silence.
    """

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    outcome: CacheOutcome = "not-modified"

    def __add__(self, other: IngestOutcome) -> IngestOutcome:
        return IngestOutcome(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
            skipped=self.skipped + other.skipped,
            outcome=max(self.outcome, other.outcome, key=_LOUDNESS.index),
        )
