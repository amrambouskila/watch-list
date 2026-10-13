"""Where an imported file belongs under the media root, and the proof it cannot be anywhere else."""

from __future__ import annotations

from datetime import date
from pathlib import Path, PurePosixPath

import pytest

from tv_watchlist.constants import (
    ILLEGAL_FILENAME_CHARACTERS,
    MAX_FILENAME_STEM_LENGTH,
    MAX_MEDIA_COMPONENT_BYTES,
)
from tv_watchlist.data.enums import MediaType
from tv_watchlist.data.errors import ImportNamingError, ImportPathError
from tv_watchlist.data.models.episode import Episode
from tv_watchlist.data.models.title import Title
from tv_watchlist.services.import_naming import assert_within, plan_destination
from tv_watchlist.services.media_filename import component_bytes

# TMDB's own ids, so the fixtures read as the works they stand for rather than as numbers.
ONE_PIECE_TMDB_ID = 37854
THE_MATRIX_TMDB_ID = 603
SPIRITED_AWAY_TMDB_ID = 129


def a_series(
    *,
    original_name: str | None = "ワンピース",
    name: str = "One Piece",
    first_air_date: date | None = date(1999, 10, 20),
) -> Title:
    """A series as the projection holds it, built in memory: naming reads attributes and nothing else."""
    return Title(
        media_type=MediaType.TV,
        tmdb_id=ONE_PIECE_TMDB_ID,
        name=name,
        original_name=original_name,
        match_key="one piece",
        first_air_date=first_air_date,
    )


def a_film(
    *,
    name: str = "The Matrix",
    original_name: str | None = None,
    first_air_date: date | None = date(1999, 3, 31),
    tmdb_id: int = THE_MATRIX_TMDB_ID,
) -> Title:
    """A film. T19's ingest writes TMDB's `release_date` into `first_air_date`, so that is the year."""
    return Title(
        media_type=MediaType.MOVIE,
        tmdb_id=tmdb_id,
        name=name,
        original_name=original_name,
        match_key="the matrix",
        first_air_date=first_air_date,
    )


def an_episode(*, season_number: int = 2, episode_number: int = 62, name: str | None = "Chase Straw Hat") -> Episode:
    return Episode(
        season_number=season_number,
        episode_number=episode_number,
        tmdb_episode_id=ONE_PIECE_TMDB_ID + episode_number,
        name=name,
    )


def a_media_root(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    root.mkdir()
    return root


def test_the_episode_template(tmp_path: Path) -> None:
    """The CLAUDE.md section 11.2 rule 9 case, stated as a reference value.

    TMDB numbers anime absolutely inside season buckets, so One Piece's season 2 runs episodes 62-77.
    `S02E62` is therefore correct and `S02E01` would be the bug: Jellyfin's TMDB provider matches the
    path against TMDB's own aired numbering, which is what the filename carries (plan decision 2).
    """
    plan = plan_destination(a_media_root(tmp_path), a_series(), an_episode(), ".mkv")

    assert plan.relative_path == PurePosixPath("TV/ワンピース/Season 02/ワンピース S02E62 - Chase Straw Hat.mkv")


def test_the_movie_template(tmp_path: Path) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_film(), None, ".mkv")

    assert plan.relative_path == PurePosixPath("Movies/The Matrix (1999)/The Matrix (1999).mkv")


def test_the_absolute_path_is_the_relative_one_resolved_under_the_media_root(tmp_path: Path) -> None:
    root = a_media_root(tmp_path)

    plan = plan_destination(root, a_series(), an_episode(), ".mkv")

    assert plan.absolute_path == root.joinpath(*plan.relative_path.parts).resolve()
    assert plan.absolute_path.is_relative_to(root.resolve())


def test_the_original_name_wins_when_tmdb_carries_one(tmp_path: Path) -> None:
    """ADR-015 decision 3, and the reason the sanitiser keeps Unicode instead of transliterating it."""
    spirited_away = a_film(
        name="Spirited Away",
        original_name="千と千尋の神隠し",
        first_air_date=date(2001, 7, 20),
        tmdb_id=SPIRITED_AWAY_TMDB_ID,
    )

    plan = plan_destination(a_media_root(tmp_path), spirited_away, None, ".mkv")

    assert plan.relative_path == PurePosixPath("Movies/千と千尋の神隠し (2001)/千と千尋の神隠し (2001).mkv")


@pytest.mark.parametrize("original_name", [None, ""])
def test_the_name_is_the_fallback_when_tmdb_carries_no_original(tmp_path: Path, original_name: str | None) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_series(original_name=original_name), an_episode(), ".mkv")

    assert plan.relative_path.parts[1] == "One Piece"


def test_a_three_digit_episode_is_not_padded_to_two(tmp_path: Path) -> None:
    plan = plan_destination(
        a_media_root(tmp_path), a_series(), an_episode(season_number=1, episode_number=1085, name=None), ".mkv"
    )

    assert plan.relative_path.name == "ワンピース S01E1085.mkv"


def test_season_zero_is_season_00(tmp_path: Path) -> None:
    """The specials bucket takes the same template as every other season, with no special case."""
    plan = plan_destination(
        a_media_root(tmp_path), a_series(), an_episode(season_number=0, episode_number=3, name=None), ".mkv"
    )

    assert plan.relative_path == PurePosixPath("TV/ワンピース/Season 00/ワンピース S00E03.mkv")


@pytest.mark.parametrize("episode_name", [None, "", "   ", "...", "/"])
def test_a_missing_episode_name_drops_the_separator_too(tmp_path: Path, episode_name: str | None) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_series(), an_episode(name=episode_name), ".mkv")

    assert plan.relative_path.name == "ワンピース S02E62.mkv"
    assert " - " not in plan.relative_path.name


def test_an_episode_title_is_sanitised_like_any_other_segment(tmp_path: Path) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_series(), an_episode(name="Luffy vs. Zoro: A Duel/Truce"), ".mkv")

    assert plan.relative_path.name == "ワンピース S02E62 - Luffy vs. Zoro A Duel Truce.mkv"


def test_a_title_with_no_first_air_date_raises_rather_than_guessing(tmp_path: Path) -> None:
    with pytest.raises(ImportNamingError, match="year"):
        plan_destination(a_media_root(tmp_path), a_film(first_air_date=None), None, ".mkv")


def test_a_series_needs_no_year_because_the_episode_template_carries_none(tmp_path: Path) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_series(first_air_date=None), an_episode(), ".mkv")

    assert plan.relative_path.parts[0] == "TV"


@pytest.mark.parametrize("suffix", [".exe", ".torrent", ".nfo", ".lnk", "", ".part", ".srt", "mkv"])
def test_an_extension_outside_the_allowlist_raises(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(ImportNamingError):
        plan_destination(a_media_root(tmp_path), a_series(), an_episode(), suffix)


@pytest.mark.parametrize("suffix", [".mkv", ".mp4", ".avi", ".MKV", ".Mp4", ".AVI", ".m4v", ".mov", ".ts", ".webm"])
def test_an_accepted_extension_is_kept_and_lowercased(tmp_path: Path, suffix: str) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_series(), an_episode(), suffix)

    assert plan.relative_path.suffix == suffix.lower()


def test_an_unconfigured_media_root_names_the_variable_that_would_configure_it() -> None:
    with pytest.raises(ImportNamingError, match="TV_MEDIA_ROOT"):
        plan_destination(None, a_series(), an_episode(), ".mkv")


def test_a_title_of_every_illegal_character_beside_a_reserved_stem_still_names(tmp_path: Path) -> None:
    hostile = a_film(name=f"CON{ILLEGAL_FILENAME_CHARACTERS}", first_air_date=date(1999, 3, 31))

    plan = plan_destination(a_media_root(tmp_path), hostile, None, ".mkv")

    assert plan.relative_path == PurePosixPath("Movies/CON_ (1999)/CON_ (1999).mkv")


@pytest.mark.parametrize("crafted", ["../../etc", "..\\..\\etc", "/etc/passwd", "C:\\Windows\\System32", "a/../../b"])
def test_a_crafted_series_name_cannot_escape_the_media_root(tmp_path: Path, crafted: str) -> None:
    """A traversal in a title is defused by the sanitiser, then the resolved path is checked anyway."""
    root = a_media_root(tmp_path)

    plan = plan_destination(root, a_series(original_name=crafted), an_episode(), ".mkv")

    assert plan.absolute_path.is_relative_to(root.resolve())
    assert all(part not in {".", ".."} for part in plan.relative_path.parts)
    assert not any(separator in part for part in plan.relative_path.parts for separator in ("/", "\\"))


@pytest.mark.parametrize("crafted", ["..", ".", "   ", "///", "..\\"])
def test_a_series_name_that_is_nothing_but_traversal_is_refused(tmp_path: Path, crafted: str) -> None:
    with pytest.raises(ImportNamingError):
        plan_destination(a_media_root(tmp_path), a_series(original_name=crafted), an_episode(), ".mkv")


def test_a_300_character_series_name_leaves_the_episode_marker_intact(tmp_path: Path) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_series(original_name="A" * 300), an_episode(), ".mkv")

    assert plan.relative_path.name.endswith(" S02E62.mkv")
    assert PurePosixPath(plan.relative_path.name).suffix == ".mkv"
    assert all(len(part) <= MAX_FILENAME_STEM_LENGTH for part in plan.relative_path.parts[:-1])
    assert len(PurePosixPath(plan.relative_path.name).stem) == MAX_FILENAME_STEM_LENGTH


def test_a_long_cjk_series_name_is_capped_in_bytes_with_the_marker_intact(tmp_path: Path) -> None:
    """R84: the compose media mount is ext4/overlay, where one component is 255 BYTES, not characters.

    A CJK glyph is three bytes, so the 113 characters the character cap would allow is 339 bytes and
    `ENAMETOOLONG` the moment T66 moves the file. The series name gives way; the marker never does.
    """
    plan = plan_destination(a_media_root(tmp_path), a_series(original_name="ワ" * 300), an_episode(), ".mkv")

    assert plan.relative_path.name.endswith(" S02E62.mkv")
    assert all(component_bytes(part) <= MAX_MEDIA_COMPONENT_BYTES for part in plan.relative_path.parts)


def test_a_long_cjk_film_title_is_capped_in_bytes_with_its_year_and_extension_intact(tmp_path: Path) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_film(name="千" * 300), None, ".mkv")

    assert plan.relative_path.name.endswith(" (1999).mkv")
    assert all(component_bytes(part) <= MAX_MEDIA_COMPONENT_BYTES for part in plan.relative_path.parts)


def test_a_long_cjk_episode_title_is_capped_in_bytes_beside_the_marker(tmp_path: Path) -> None:
    plan = plan_destination(
        a_media_root(tmp_path), a_series(original_name="One Piece"), an_episode(name="冒" * 300), ".mkv"
    )

    assert plan.relative_path.name.startswith("One Piece S02E62 - ")
    assert all(component_bytes(part) <= MAX_MEDIA_COMPONENT_BYTES for part in plan.relative_path.parts)


def test_a_300_character_film_title_is_capped_with_its_year_and_extension_intact(tmp_path: Path) -> None:
    plan = plan_destination(a_media_root(tmp_path), a_film(name="A" * 300), None, ".mkv")

    stem = PurePosixPath(plan.relative_path.name).stem
    assert stem.endswith(" (1999)")
    assert len(stem) == MAX_FILENAME_STEM_LENGTH
    assert plan.relative_path.parts[1] == stem
    assert plan.relative_path.suffix == ".mkv"


def test_a_long_episode_title_is_trimmed_to_fit_beside_the_marker(tmp_path: Path) -> None:
    plan = plan_destination(
        a_media_root(tmp_path), a_series(original_name="One Piece"), an_episode(name="B" * 300), ".mkv"
    )

    stem = PurePosixPath(plan.relative_path.name).stem
    assert stem.startswith("One Piece S02E62 - ")
    assert len(stem) == MAX_FILENAME_STEM_LENGTH


def test_an_episode_title_is_dropped_when_a_long_series_name_leaves_it_no_room(tmp_path: Path) -> None:
    plan = plan_destination(
        a_media_root(tmp_path), a_series(original_name="ワ" * 300), an_episode(name="Romance Dawn"), ".mkv"
    )

    assert " - " not in plan.relative_path.name


def test_assert_within_returns_the_resolved_path(tmp_path: Path) -> None:
    root = a_media_root(tmp_path)
    inside = root / "TV" / "One Piece" / "x.mkv"

    assert assert_within(inside, root) == inside.resolve()


@pytest.mark.parametrize("escape", ["dot_dot", "absolute", "symlink", "the_root_itself"])
def test_assert_within_refuses_an_escape(tmp_path: Path, escape: str) -> None:
    """`resolve()` follows symlinks, which is exactly why containment is checked on the resolved path."""
    root = a_media_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    candidates = {
        "dot_dot": root / ".." / "outside" / "x.mkv",
        "absolute": outside / "x.mkv",
        "symlink": root / "escape" / "x.mkv",
        "the_root_itself": root,
    }

    with pytest.raises(ImportPathError):
        assert_within(candidates[escape], root)


def test_assert_within_refuses_a_path_carrying_a_null_byte(tmp_path: Path) -> None:
    """`resolve()` raises `ValueError` on an embedded null, which is a refusal here rather than a crash."""
    root = a_media_root(tmp_path)

    with pytest.raises(ImportPathError):
        assert_within(root / "TV" / "x\x00y.mkv", root)
