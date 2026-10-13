"""The sanitiser: what a title the owner curated becomes before it is allowed to be a path component."""

from __future__ import annotations

import unicodedata

import pytest

from tv_watchlist.constants import (
    ILLEGAL_FILENAME_CHARACTERS,
    MAX_FILENAME_STEM_LENGTH,
    MAX_MEDIA_COMPONENT_BYTES,
    RESERVED_FILENAME_STEMS,
)
from tv_watchlist.data.errors import ImportNamingError
from tv_watchlist.services.media_filename import component_bytes, optional_component, safe_component

# The four a returned component may never carry. `..` is not in the list on purpose: an interior pair of
# dots is a legal filename (`Hello... World`), and the traversal hazard is a component that IS `..`,
# which is asserted separately.
FORBIDDEN: tuple[str, ...] = ("/", "\\", "\x00", "\n")
TRAVERSALS: frozenset[str] = frozenset({".", ".."})


def assert_carries_nothing_a_path_could_use(component: str) -> None:
    """Every invariant `safe_component` promises, in one place so each test asserts the same thing."""
    assert not any(forbidden in component for forbidden in FORBIDDEN)
    assert component not in TRAVERSALS
    assert component == component.strip(" .")
    assert component != ""


@pytest.mark.parametrize(
    "value",
    [
        "a/b",
        "a\\b",
        "../etc",
        "..\\..\\x",
        "a\x00b",
        "a\nb",
        "a\tb",
        "CON",
        "nul",
        "trailing.",
        "trailing ",
        " leading",
        "Blade II: Bloodhunt",
        'a"b<c>d|e?f*g',
        "/etc/passwd",
        "C:\\Windows\\System32",
    ],
)
def test_a_separator_never_survives(value: str) -> None:
    assert_carries_nothing_a_path_could_use(safe_component(value))


@pytest.mark.parametrize("value", ["..", ".", "...", " ", "", "   ", "///", "\\\\", '<>:"/\\|?*', "\x00\n\t"])
def test_a_value_with_nothing_a_filesystem_can_hold_is_refused(value: str) -> None:
    """`..` alone is the case that matters: reduced to nothing, it is refused rather than emitted."""
    with pytest.raises(ImportNamingError):
        safe_component(value)


@pytest.mark.parametrize("value", ["ワンピース", "Pokémon", "進撃の巨人", "Æon Flux", "Amélie", "鋼の錬金術師"])
def test_unicode_survives(value: str) -> None:
    """ADR-015 decision 3 names a title by `original_name`, so a non-ASCII name must come back intact."""
    assert safe_component(value) == value


def test_a_decomposed_name_is_normalised_to_one_codepoint_per_glyph() -> None:
    decomposed = unicodedata.normalize("NFD", "Pokémon")

    assert decomposed != "Pokémon"
    assert safe_component(decomposed) == "Pokémon"


def test_a_colon_is_replaced_not_refused() -> None:
    """`workbook/stem.validate_stem` refuses a colon; a real title legally carries one, so this replaces."""
    assert safe_component("Star Wars: Episode II") == "Star Wars Episode II"


def test_an_illegal_character_becomes_a_space_rather_than_welding_two_words_together() -> None:
    assert safe_component("Face/Off") == "Face Off"


@pytest.mark.parametrize("stem", sorted(RESERVED_FILENAME_STEMS))
def test_a_reserved_stem_gains_a_suffix_rather_than_naming_a_windows_device(stem: str) -> None:
    assert safe_component(stem) == f"{stem}_"
    assert safe_component(stem.upper()) == f"{stem.upper()}_"


def test_a_reserved_stem_reached_through_sanitising_is_caught_too() -> None:
    assert safe_component("  con.  ") == "con_"


def test_a_name_that_merely_starts_with_a_reserved_stem_is_left_alone() -> None:
    assert safe_component("Conan the Barbarian") == "Conan the Barbarian"


def test_a_long_title_is_capped_at_the_constant() -> None:
    assert len(safe_component("A" * 300)) == MAX_FILENAME_STEM_LENGTH


def test_truncation_does_not_leave_a_trailing_dot_or_space() -> None:
    """Windows silently drops a trailing dot, so a path recorded with one would never find its file."""
    component = safe_component("A" * (MAX_FILENAME_STEM_LENGTH - 1) + ". tail")

    assert component == "A" * (MAX_FILENAME_STEM_LENGTH - 1)


@pytest.mark.parametrize("limit", [1, 5, 40, MAX_FILENAME_STEM_LENGTH])
def test_the_limit_is_honoured_on_a_character_boundary(limit: int) -> None:
    # Four bytes is the widest a single code point can be, so this budget can never be what binds here.
    component = safe_component("ワンピース" * 40, limit=limit, limit_bytes=limit * 4)

    assert len(component) == limit


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        ("con", 3, "co_"),
        ("CONtact", 3, "CO_"),
        ("com1x", 4, "com_"),
        ("NULl", 3, "NU_"),
        ("con", MAX_FILENAME_STEM_LENGTH, "con_"),
        ("CONtact", MAX_FILENAME_STEM_LENGTH, "CONtact"),
    ],
)
def test_a_reserved_stem_the_cap_itself_manufactured_is_still_caught(value: str, limit: int, expected: str) -> None:
    """The guard runs AFTER the cap, or truncation cuts the suffix back off or makes a device name.

    `CONtact` capped to three characters IS `CON`, which Windows refuses to carry; appending first and
    truncating second gives `con` back at a limit of three. Both are paths T66 would fail to write.
    """
    component = safe_component(value, limit=limit)

    assert component == expected
    assert len(component) <= limit
    assert component.lower() not in RESERVED_FILENAME_STEMS


def test_a_reserved_stem_the_cap_manufactured_is_caught_in_the_optional_form_too() -> None:
    assert optional_component("NULl", limit=3) == "NU_"


def test_a_component_is_capped_in_bytes_as_well_as_characters() -> None:
    """A CJK glyph is three bytes, so 113 characters is 339 - ENAMETOOLONG on ext4, APFS and NTFS."""
    component = safe_component("ワ" * 300)

    assert component_bytes(component) <= MAX_MEDIA_COMPONENT_BYTES
    assert len(component) < MAX_FILENAME_STEM_LENGTH


@pytest.mark.parametrize("limit_bytes", range(1, 20))
def test_the_byte_cap_never_splits_a_code_point(limit_bytes: int) -> None:
    """A cut inside a three-byte sequence leaves an invalid name, so whole glyphs are dropped instead."""
    component = optional_component("ワ" * 10, limit_bytes=limit_bytes)

    assert component == "ワ" * (limit_bytes // 3) or component is None


@pytest.mark.parametrize("limit_bytes", [0, -3])
def test_optional_component_is_none_when_no_bytes_are_left(limit_bytes: int) -> None:
    assert optional_component("Romance Dawn", limit_bytes=limit_bytes) is None


def test_no_value_in_a_hostile_corpus_ever_carries_a_separator() -> None:
    """The stated property, over every two-character mix of the hostile alphabet around a safe core."""
    alphabet = f"{ILLEGAL_FILENAME_CHARACTERS}. \x00\n\tA1ワ"

    for first in alphabet:
        for second in alphabet:
            assert_carries_nothing_a_path_could_use(safe_component(f"{first}{second}x{second}{first}"))


def test_optional_component_keeps_a_real_name() -> None:
    assert optional_component("Romance Dawn") == "Romance Dawn"


@pytest.mark.parametrize("value", [None, "", "...", "   ", "/"])
def test_optional_component_is_none_when_there_is_nothing_to_name(value: str | None) -> None:
    """An absent or punctuation-only episode title drops the segment, never leaves a dangling dash."""
    assert optional_component(value) is None


@pytest.mark.parametrize("limit", [0, -3])
def test_optional_component_is_none_when_no_room_is_left_beside_the_marker(limit: int) -> None:
    assert optional_component("Romance Dawn", limit=limit) is None


def test_optional_component_honours_a_room_limit_it_can_meet() -> None:
    assert optional_component("Romance Dawn", limit=7) == "Romance"
