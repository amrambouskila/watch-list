"""Every page of one ordering, flattened."""

from __future__ import annotations

from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode
from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbEpisodesResult(TvdbPayload):
    """The pages a walk read, and whether what came back means anything at all."""

    episodes: tuple[TvdbEpisode, ...] = ()
    pages: int = 0
    # What the service said the ordering holds, against what the walk collected. The two disagree when a
    # walk was cut short, which is the one failure that otherwise looks exactly like success
    # (CLAUDE.md section 9.2). `None` means the pages carried no count to compare against, which is not
    # the same claim as zero.
    reported: int | None = None

    @property
    def known(self) -> bool:
        """False when the array came back empty: UNKNOWN, mutate nothing - never "this series has no episodes"."""
        # A property rather than a field, so no call site can construct a result that claims an empty
        # ordering was a known-empty one. An unrecognised season type answers HTTP 200 with `episodes: []`,
        # and a plugin that read that as authoritative deleted 194 seasons a scan.
        return bool(self.episodes)
