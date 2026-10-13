"""Release filenames have their own grammar, separate from workbook spans."""

from __future__ import annotations

import pytest

from tv_watchlist.services.import_filename import parse_filename


@pytest.mark.parametrize(
    ("name", "token", "year", "season", "episode", "absolute", "confidence"),
    [
        ("Series.S01E02.1080p.WEB-DL.mkv", "Series", None, 1, 2, None, 0.95),
        ("[Group] Series.s00e03.x265.MKV", "Series", None, 0, 3, None, 0.95),
        ("Series_Name_S12E100.mkv", "Series Name", None, 12, 100, None, 0.95),
        ("Series (2020) S01E02 - Episode title.mkv", "Series", 2020, 1, 2, None, 0.95),
        ("Series.2020.S01E02.mkv", "Series", 2020, 1, 2, None, 0.95),
        ("[Group] One Piece - 1085 (1080p) [ABCDEF12].mkv", "One Piece", None, None, None, 1085, 0.90),
        ("Series - 1085v2.mkv", "Series", None, None, None, 1085, 0.90),
        ("Series - 01 - Episode Name.mkv", "Series", None, None, None, 1, 0.90),
        ("Series 1x02 720p.mkv", "Series", None, 1, 2, None, 0.90),
        ("Series.0X01.WEBRip.mp4", "Series", None, 0, 1, None, 0.90),
        ("The Matrix (1999).mkv", "The Matrix", 1999, None, None, None, 0.95),
        ("[Group] The.Matrix.1999.1080p.BluRay.x264.ABCDEF12.mkv", "The Matrix", 1999, None, None, None, 0.85),
        ("Film_Title_1999_HEVC.mp4", "Film Title", 1999, None, None, None, 0.85),
        ("Film (1999) [1080p] [x265].mp4", "Film", 1999, None, None, None, 0.95),
        ("Pokémon.S01E00.mkv", "Pokémon", None, 1, 0, None, 0.95),
        ("Series S01E02", "Series", None, 1, 2, None, 0.95),
        ("Series 1080p x264 S01E02.mkv", "Series", None, 1, 2, None, 0.95),
        ("1917 (2019).mkv", "1917", 2019, None, None, None, 0.95),
        ("Blade.Runner.2049.2017.1080p.mkv", "Blade Runner 2049", 2017, None, None, None, 0.85),
        ("2001.A.Space.Odyssey.1968.1080p.mkv", "2001 A Space Odyssey", 1968, None, None, None, 0.85),
        ("1899.S01E02.mkv", "1899", None, 1, 2, None, 0.95),
        ("2001.A.Space.Odyssey.S01E02.mkv", "2001 A Space Odyssey", None, 1, 2, None, 0.95),
        ("Series.S01E02 - Episode 1984.mkv", "Series", None, 1, 2, None, 0.95),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_recognised_release_shapes(
    name: str,
    token: str,
    year: int | None,
    season: int | None,
    episode: int | None,
    absolute: int | None,
    confidence: float,
) -> None:
    parsed = parse_filename(name)
    assert parsed.model_dump(exclude={"confidence"}) == {
        "series_token": token,
        "year": year,
        "season_number": season,
        "episode_number": episode,
        "absolute_number": absolute,
    }
    assert parsed.confidence == pytest.approx(confidence)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "random media.mkv",
        "[Group] [1080p] [ABCDEF12].mkv",
        "S01E02.mkv",
        "(1999).mkv",
        "東京.1999.mkv",
        "1080p (1999).mkv",
        "Series - 0.mkv",
        "../Series.S01E02.mkv",
        r"C:\Series.S01E02.mkv",
        "Series\x00.S01E02.mkv",
        "Series.S01E02E03.mkv",
        "Series.S01E02-E03.mkv",
        "Series.S01E02-03.mkv",
        "Series.S01E02.S01E03.mkv",
        "Series.S01E02+03.mkv",
        "Series.S01E02 & 03.mkv",
        "Series.S01E02 to 03.mkv",
        "Series.1x02x03.mkv",
        "Series.1x02-03.mkv",
        "Series.1x02.1x03.mkv",
        "Series - 1085-1086.mkv",
        "Series - 1085v2-1086.mkv",
        "Series - 1085 + 1086.mkv",
        "Series - 1085 & 1086.mkv",
        "Series - 1085 to 1086.mkv",
        "Series.S01E02000.mkv",
        "Series - 123456.mkv",
        "Series S01E02 and S01E03.mkv",
        "Series.S01E02.1x03.mkv",
        "Series.1x02.S01E03.mkv",
        "Series.S01E02.03.mkv",
        "Series - 1085 1086.mkv",
        "Film (1999) (2000).mkv",
        "Film.1999-2000.mkv",
        "Film.1999.to.2000.mkv",
        "Series - 1085 S01E02.mkv",
        "Series - 1085 1x02.mkv",
    ],
    ids=lambda name: name or "empty",
)
def test_unrecognised_or_multi_episode_names_refuse_to_guess(name: str) -> None:
    parsed = parse_filename(name)
    assert parsed.series_token == ""
    assert parsed.year is parsed.season_number is parsed.episode_number is parsed.absolute_number is None
    assert parsed.confidence == pytest.approx(0)


def test_a_release_group_bracket_never_becomes_the_series_token() -> None:
    assert parse_filename("[Very Famous Group] Actual Series - 12.mkv").series_token == (
        "Actual Series"  # noqa: S105 - a title fragment, not an authentication token
    )
