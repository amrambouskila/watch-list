"""What a downloaded hero image is, decided by its own bytes and by nothing else."""

from __future__ import annotations

import pytest
from sample_images import (
    GIF87,
    GIF89,
    HTML_PAGE,
    JPEG,
    PNG,
    RIFF_AUDIO,
    SVG_BARE,
    SVG_DOCUMENT,
    TRUNCATED_PNG,
    WEBP,
)

from tv_watchlist.constants import HERO_SUFFIXES
from tv_watchlist.services.image_format import image_suffix


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, ".png"),
        (JPEG, ".jpg"),
        (GIF87, ".gif"),
        (GIF89, ".gif"),
        (WEBP, ".webp"),
    ],
)
def test_each_accepted_raster_format_is_named_from_its_magic_bytes(data: bytes, expected: str) -> None:
    assert image_suffix(data) == expected


@pytest.mark.parametrize("data", [SVG_DOCUMENT, SVG_BARE])
def test_svg_is_refused_because_it_is_scriptable_xml_not_a_raster_image(data: bytes) -> None:
    assert image_suffix(data) is None


@pytest.mark.parametrize("data", [HTML_PAGE, RIFF_AUDIO, TRUNCATED_PNG, b""])
def test_anything_that_is_not_one_of_the_accepted_formats_is_refused(data: bytes) -> None:
    assert image_suffix(data) is None


def test_every_suffix_it_returns_is_one_the_card_looks_for() -> None:
    assert {image_suffix(data) for data in (PNG, JPEG, GIF89, WEBP)} <= set(HERO_SUFFIXES)
