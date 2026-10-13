"""What the Postgres projection refuses to do, and why each refusal is an answer rather than a crash.

These are the projection's own failures - distinct from `workbook.errors`, which speaks for the `.xlsx`
files, and from `clients.errors`, which never reaches a response at all. Every class here IS registered
in `api/errors.py`'s two tables, because a route does reach them; one that is not silently becomes a 400
carrying `str(error)` as its whole message (CLAUDE.md section 4.3). (T68 registers `ImportNamingError`
and `ImportPathError`, which T63 added here ahead of the routes that raise them.)
"""

from __future__ import annotations


class ProjectionError(Exception):
    """Base class for failures of the derived Postgres projection."""


class EntryNotFoundError(ProjectionError):
    """No live curated entry answers to that id - it never existed, or the sheet dropped its row."""


class ResolutionConflictError(ProjectionError):
    """The review decision cannot be applied as it was asked for, so nothing about the entry was changed.

    A conflict, not a bad request: the body was coherent and the entry is real, but the world it names is
    not there - no provider is configured, TMDB has nothing under that id, or the title carries no such
    numbering. Every one of those is worth retrying once something has changed, which is what 409 says.
    """


class WatchSubjectNotFoundError(ProjectionError):
    """The episode, title or curated entry a watch event names is not in the projection.

    Resolved before anything is inserted, so an id nothing answers to is a 404 the caller can act on
    rather than the integrity error `one_subject` would otherwise raise several frames deeper.
    """


class JellyfinUnavailableError(ProjectionError):
    """Jellyfin is unconfigured or did not answer, so the library index was not touched at all.

    A `ProjectionError` rather than the `ProviderError` the client raised, and that conversion is the
    point (R72): `clients.errors` is deliberately unregistered in `api/errors.py`, because a provider
    failure belongs in `sync_state.last_error` rather than in a response - but `POST /api/library/sync`
    IS a route, and it promises "a disabled feature, never a 500". This is the class that promise is
    kept with, and it carries only the upstream failure's class NAME: the client's own messages are
    built the same way, because a key holding a CR or an LF arrives inside h11's complaint about it.
    """


class PlaybackItemNotFoundError(ProjectionError):
    """No live movie or episode file answers to the app-owned item UUID."""


class PlaybackRangeError(ProjectionError):
    """The requested byte range cannot be forwarded safely."""


class PlaybackUpstreamError(ProjectionError):
    """A healthy Jellyfin could not supply the stream; only a safe failure class may leave the client."""


class PlaybackStateError(ProjectionError):
    """A playback snapshot no longer matches its selected subject, file or current progress."""


class ImportNamingError(ProjectionError):
    """No destination path can be composed for this file, so nothing about it is moved.

    Every reason is a fact the projection is missing rather than a caller's mistake: no media root is
    configured, a film carries no release year, an extension this app does not import, or a title that
    sanitises away to nothing. The row goes `failed` carrying the message, which is the same "never
    invent" rule the resolver applies to a `Unit` cell it cannot parse - a guessed path names a file
    Jellyfin will never match, and looks right while doing it.
    """


class ImportPathError(ProjectionError):
    """A path that resolved outside the media root, refused before a single byte was moved.

    Raised on the RESOLVED path, never the joined one: `resolve()` follows symlinks, so a link inside
    the media root pointing out of it is exactly the escape a joined-path check waves through
    (CLAUDE.md section 10.3, B22). The media root itself is refused too - a file lives under the root,
    it is never the root.
    """
