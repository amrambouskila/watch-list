from __future__ import annotations

from tv_watchlist.ingest.errors import IngestRefusedError


class EpisodeOrderBusyError(IngestRefusedError):
    """Numbering contention refuses the entire ingest transaction, including earlier metadata writes."""
