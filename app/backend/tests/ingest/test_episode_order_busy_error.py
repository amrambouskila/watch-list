from __future__ import annotations

from tv_watchlist.ingest.episode_order_busy_error import EpisodeOrderBusyError
from tv_watchlist.ingest.errors import IngestRefusedError


def test_numbering_contention_uses_the_existing_whole_ingest_refusal_boundary() -> None:
    refusal = EpisodeOrderBusyError("retry")
    assert isinstance(refusal, IngestRefusedError)
    assert str(refusal) == "retry"
