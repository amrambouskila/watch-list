"""Where an imported file belongs under the media root, and the check that it cannot be anywhere else."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from tv_watchlist.constants import (
    MAX_FILENAME_STEM_LENGTH,
    MAX_MEDIA_COMPONENT_BYTES,
    MEDIA_EPISODE_STEM_TEMPLATE,
    MEDIA_EPISODE_TITLE_TEMPLATE,
    MEDIA_IMPORT_EXTENSIONS,
    MEDIA_IMPORT_MOVIES_DIRNAME,
    MEDIA_IMPORT_TV_DIRNAME,
    MEDIA_MOVIE_STEM_TEMPLATE,
    MEDIA_NUMBER_PAD_WIDTH,
    MEDIA_SEASON_DIRNAME_TEMPLATE,
)
from tv_watchlist.data.errors import ImportNamingError, ImportPathError
from tv_watchlist.services.media_filename import component_bytes, optional_component, safe_component

if TYPE_CHECKING:
    from tv_watchlist.data.models.episode import Episode
    from tv_watchlist.data.models.title import Title


@dataclass(frozen=True, slots=True)
class DestinationPlan:
    """Where one imported file lands: the relative path a row stores, and the resolved absolute one."""

    relative_path: PurePosixPath
    absolute_path: Path


def assert_within(path: Path, root: Path) -> Path:
    """`path.resolve()`, refused with `ImportPathError` unless it is inside `root.resolve()`."""
    try:
        resolved = path.resolve()
        base = root.resolve()
    except ValueError as error:
        # An embedded null byte: `resolve()` raises rather than returning, and an unhandled ValueError
        # here would leave the caller with a bare crash instead of the refusal every other bad path gets.
        raise ImportPathError(f"{path!r} is not a path this filesystem can resolve") from error
    # Checked on the RESOLVED path, never the joined one: `resolve()` follows symlinks, and a link
    # inside the media root pointing out of it is precisely the escape a joined-path check waves
    # through. The root itself is refused as well - a file lives under the root, it is never the root.
    if resolved == base or not resolved.is_relative_to(base):
        raise ImportPathError(f"{path} resolves outside {root}")
    return resolved


def plan_destination(
    media_root: Path | None, title: Title, episode: Episode | None, source_suffix: str
) -> DestinationPlan:
    """The destination one imported file takes, composed from projection values and nothing else.

    Never from the source filename: the whole point of the convention is that Jellyfin matches the path
    against TMDB's own numbering, which only the projection holds.
    """
    if media_root is None:
        raise ImportNamingError("TV_MEDIA_ROOT is not configured, so no import destination can be named")
    suffix = source_suffix.lower()
    if suffix not in MEDIA_IMPORT_EXTENSIONS:
        raise ImportNamingError(f"{source_suffix!r} is not a media extension this app imports")
    # `original_name` when TMDB carries one (ADR-015 decision 3), which is why the sanitiser keeps
    # Unicode rather than transliterating: One Piece is filed under its own name.
    display_name = title.original_name or title.name
    relative = (
        _movie_path(display_name, title, suffix) if episode is None else _episode_path(display_name, episode, suffix)
    )
    # Composed, then checked anyway. A component the sanitiser passed cannot carry a separator, so this
    # can only fire on a media root that is itself a link out of somewhere - and it fires before the
    # caller is handed a path it would move bytes to.
    return DestinationPlan(
        relative_path=relative, absolute_path=assert_within(media_root.joinpath(*relative.parts), media_root)
    )


def _episode_path(display_name: str, episode: Episode, suffix: str) -> PurePosixPath:
    """`TV/<Series Name>/Season <nn>/<Series Name> S<nn>E<nn> - <episode title>.<ext>`."""
    numbering = {
        "season": episode.season_number,
        "episode": episode.episode_number,
        "width": MEDIA_NUMBER_PAD_WIDTH,
    }
    # The template formatted with an empty series measures its own decoration, so the marker's width is
    # read off the template rather than counted by hand and drifting when the template changes. The
    # extension counts against the byte cap too: the capped component is the whole filename, not the
    # stem, and the series name is what gives way so the marker Jellyfin matches on never does.
    marker = MEDIA_EPISODE_STEM_TEMPLATE.format(series="", **numbering)
    series = safe_component(
        display_name,
        limit=MAX_FILENAME_STEM_LENGTH - len(marker),
        limit_bytes=MAX_MEDIA_COMPONENT_BYTES - component_bytes(marker) - component_bytes(suffix),
    )
    stem = MEDIA_EPISODE_STEM_TEMPLATE.format(series=series, **numbering)
    # The episode title takes whatever room is left beside the marker, and is dropped along with its
    # separator when there is none - the marker is what Jellyfin matches on, the title is decoration.
    separator = MEDIA_EPISODE_TITLE_TEMPLATE.format(stem="", episode_title="")
    spent_bytes = component_bytes(stem) + component_bytes(separator) + component_bytes(suffix)
    episode_title = optional_component(
        episode.name,
        limit=MAX_FILENAME_STEM_LENGTH - len(stem) - len(separator),
        limit_bytes=MAX_MEDIA_COMPONENT_BYTES - spent_bytes,
    )
    if episode_title is not None:
        stem = MEDIA_EPISODE_TITLE_TEMPLATE.format(stem=stem, episode_title=episode_title)
    season = safe_component(MEDIA_SEASON_DIRNAME_TEMPLATE.format(**numbering))
    return PurePosixPath(MEDIA_IMPORT_TV_DIRNAME, series, season, f"{stem}{suffix}")


def _movie_path(display_name: str, title: Title, suffix: str) -> PurePosixPath:
    """`Movies/<Title> (<year>)/<Title> (<year>).<ext>`, with the directory and the file the same stem."""
    if title.first_air_date is None:
        # T19's ingest writes a film's TMDB `release_date` into `first_air_date`, so an absent one means
        # TMDB has no release date either. The row goes `failed` rather than being filed under a guessed
        # year, because a year nobody chose is a path Jellyfin matches to the wrong work.
        raise ImportNamingError(f"{display_name!r} carries no release date, and a film is not named without its year")
    year = title.first_air_date.year
    decoration = MEDIA_MOVIE_STEM_TEMPLATE.format(title="", year=year)
    stem = MEDIA_MOVIE_STEM_TEMPLATE.format(
        title=safe_component(
            display_name,
            limit=MAX_FILENAME_STEM_LENGTH - len(decoration),
            limit_bytes=MAX_MEDIA_COMPONENT_BYTES - component_bytes(decoration) - component_bytes(suffix),
        ),
        year=year,
    )
    return PurePosixPath(MEDIA_IMPORT_MOVIES_DIRNAME, stem, f"{stem}{suffix}")
