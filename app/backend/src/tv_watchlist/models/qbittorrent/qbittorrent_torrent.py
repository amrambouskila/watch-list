"""One torrent as qBittorrent's `GET /api/v2/torrents/info` reports it."""

from __future__ import annotations

import re
from typing import Final

from pydantic import Field

from tv_watchlist.constants import (
    MAX_QBITTORRENT_HASH_LENGTH,
    MAX_QBITTORRENT_NAME_LENGTH,
    MAX_QBITTORRENT_PATH_LENGTH,
    MAX_QBITTORRENT_STATE_LENGTH,
    QBITTORRENT_HASH_PATTERN,
)
from tv_watchlist.models.qbittorrent.qbittorrent_payload import QbittorrentPayload

# Compiled ONCE, here, and read through `is_recognised_hash` by both the row below and the client that
# puts a hash in a URL - so "what this project will accept as an infohash" has a single answer (R85).
_HASH_SHAPE: Final[re.Pattern[str]] = re.compile(QBITTORRENT_HASH_PATTERN)


def is_recognised_hash(value: str) -> bool:
    """Whether this is an infohash this project will act on: 40 lowercase hex (v1) or 64 (v2)."""
    return _HASH_SHAPE.fullmatch(value) is not None


class QbittorrentTorrent(QbittorrentPayload):
    """The nine documented fields the import scan reads. Nothing here is interpreted; it is carried.

    `save_path` and `content_path` are both absolute and they are NOT interchangeable: `content_path` is
    documented as "root path for multifile torrents, absolute file path for singlefile torrents", while a
    file's own `name` is relative to `save_path`. `QbittorrentFile.absolute_path` is where that matters and
    is the one place the join is made.

    Only `hash` is required, and that is a decision rather than an oversight: a torrent with no hash is one
    nothing could be asked about, so failing loudly on it beats storing a blank.
    """

    hash: str = Field(max_length=MAX_QBITTORRENT_HASH_LENGTH)
    name: str = Field(default="", max_length=MAX_QBITTORRENT_NAME_LENGTH)
    # "Absolute path of torrent content (root path for multifile torrents, absolute file path for
    # singlefile torrents)" - exposed since WebAPI v2.6.1, which is half of why the version floor exists.
    content_path: str = Field(default="", max_length=MAX_QBITTORRENT_PATH_LENGTH)
    # "Path where this torrent's data is stored" - the directory a file's relative `name` hangs off.
    save_path: str = Field(default="", max_length=MAX_QBITTORRENT_PATH_LENGTH)
    state: str = Field(default="", max_length=MAX_QBITTORRENT_STATE_LENGTH)
    # "Torrent progress (percentage/100)", so a finished torrent is 1.0 rather than 100.
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    # "Time (Unix Epoch) when the torrent completed" - and qBittorrent reports -1 for one that has not, so
    # this is deliberately NOT bounded at zero: bounding it would refuse a body the server really sends.
    completion_on: int = 0
    size: int = Field(default=0, ge=0)
    amount_left: int = Field(default=0, ge=0)

    @property
    def has_recognised_hash(self) -> bool:
        """Whether this row's hash is one the client will put in a URL - the skip predicate, exposed once.

        `hash` is NOT validated against the pattern, deliberately: a torrent whose hash this project does
        not recognise is still a torrent the server listed, and refusing the whole body over one row would
        turn one odd torrent into a failed import pass. An import scan reads this, skips the row as
        `unrecognised_hash` and carries on (R85).
        """
        return is_recognised_hash(self.hash)
