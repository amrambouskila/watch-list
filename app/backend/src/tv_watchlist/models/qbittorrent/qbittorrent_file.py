"""One file inside a torrent, as qBittorrent's `GET /api/v2/torrents/files` reports it."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

from pydantic import Field, field_validator

from tv_watchlist.constants import MAX_QBITTORRENT_PATH_LENGTH, TRAVERSAL_SEGMENT
from tv_watchlist.models.qbittorrent.qbittorrent_payload import QbittorrentPayload

# Both separators, because a qBittorrent on Windows reports backslashes and a name ending in either one
# is a directory rather than a file.
_SEPARATORS: Final[frozenset[str]] = frozenset({"/", "\\"})
# Everything below U+0020 - NUL, CR and LF among them. A name carrying one would forge a log record, and
# on most filesystems it cannot be created at all.
_FIRST_PRINTABLE: Final[str] = " "


class QbittorrentFile(QbittorrentPayload):
    """The five documented fields the import scan reads, plus the one rule that is easy to get wrong.

    `index` is required because it is the field the client's 2.8.2 version floor exists for ("File index",
    since 2.8.2); a body without one came from a server too old to be read at all.
    """

    index: int = Field(ge=0)
    # "File name (including relative path)" - relative to the TORRENT'S `save_path`. See `absolute_path`.
    name: str = Field(max_length=MAX_QBITTORRENT_PATH_LENGTH)
    size: int = Field(default=0, ge=0)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _a_name_may_not_walk_out_of_the_save_path(cls, value: str) -> str:
        """A torrent's file names are attacker-supplied, and the import pipeline joins them to a directory.

        Refusing here, at the boundary, is what makes `absolute_path` unable to escape - so no caller has
        to remember a containment check. Both path flavours are checked because a qBittorrent on Windows
        reports backslashes, which `PurePosixPath` reads as one harmless-looking segment.

        `anchor` rather than `is_absolute()`: on Windows a path can be ROOTED without being absolute, so
        a leading backslash has no drive and `is_absolute()` answers `False` - while joining it to
        `C:/staging` still yields `C:/evil.mkv`. `anchor` is the drive and the root together, which is
        the thing that actually matters here.
        """
        if not value:
            raise ValueError("a file name may not be empty")
        if any(character < _FIRST_PRINTABLE for character in value):
            raise ValueError("a file name may not carry a control character")
        posix, windows = PurePosixPath(value), PureWindowsPath(value)
        if posix.anchor or windows.anchor:
            raise ValueError("a file name must be relative to the torrent's save_path")
        if TRAVERSAL_SEGMENT in posix.parts or TRAVERSAL_SEGMENT in windows.parts:
            raise ValueError("a file name may not walk out of the torrent's save_path")
        # A name that normalises to something else is a name that would be JOINED as something else, and
        # one ending in a separator, or resolving to no filename at all, names a directory rather than a
        # file. Either way it is not the thing this row claims to be.
        if value[-1] in _SEPARATORS or str(posix) != value or not posix.name:
            raise ValueError("a file name must name a file, not a directory")
        return value

    def absolute_path(self, save_path: Path) -> Path:
        """The file on disk: `save_path / name`, and this is the ONE place that rule is applied.

        The WebUI API documents `name` as "File name (including relative path)", relative to the torrent's
        `save_path`. It is NOT relative to `content_path`, which for a multifile torrent is already the
        torrent's own root directory - so `content_path / name` repeats that directory and names a path
        that does not exist. The two constructions agree for a singlefile torrent and disagree for every
        other one, which is exactly why the wrong one looks right
        (`tests/models/test_qbittorrent_models.py` shows it being wrong against the recorded body).
        """
        return save_path / self.name
