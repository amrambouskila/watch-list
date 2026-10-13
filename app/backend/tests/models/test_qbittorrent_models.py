"""The two qBittorrent response models, checked against the hand-authored bodies field for field.

The fixtures are not recordings (`tests/fixtures/qbittorrent/README.md` says why), so a body that drifted
from the documented shape would otherwise make every client test pass against nothing. These tests are the
counterweight: every field the client reads must be present in the fixture, spelled the way the WebUI API
wiki page spells it.

They also pin the one rule that is easy to get plausibly wrong: a file's `name` is *"File name (including
relative path)"* relative to the torrent's **`save_path`**, so the absolute path is `save_path / name` and
never `content_path / name`.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Final

import pytest
from pydantic import BaseModel, ValidationError

from provider_fixtures import QBITTORRENT, fixture_rows
from tv_watchlist.models.qbittorrent.qbittorrent_file import QbittorrentFile
from tv_watchlist.models.qbittorrent.qbittorrent_torrent import QbittorrentTorrent, is_recognised_hash

# Exactly the fields the client reads off each body. `category`, `tags`, `ratio` and the rest are in the
# fixtures deliberately and are NOT here: a field with no consumer is a stub (Ruling 12).
TORRENT_FIELDS: Final[tuple[str, ...]] = (
    "hash",
    "name",
    "content_path",
    "save_path",
    "state",
    "progress",
    "completion_on",
    "size",
    "amount_left",
)
FILE_FIELDS: Final[tuple[str, ...]] = ("index", "name", "size", "progress", "priority")
A_SAVE_PATH: Final[Path] = Path("/staging/downloads")


def _a_file(**overrides: object) -> dict[str, object]:
    """One documented file row, with whatever a test needs changed."""
    return {"index": 0, "name": "Some.Show.S01E01.mkv", "size": 1, "progress": 1, "priority": 1} | overrides


@pytest.mark.parametrize("field", TORRENT_FIELDS)
def test_every_documented_torrent_field_is_present_in_the_fixture(field: str) -> None:
    for row in fixture_rows(QBITTORRENT, "torrents_info_completed"):
        assert field in row


@pytest.mark.parametrize("field", FILE_FIELDS)
@pytest.mark.parametrize("body", ["torrents_files_multi", "torrents_files_single"])
def test_every_documented_file_field_is_present_in_the_fixture(field: str, body: str) -> None:
    for row in fixture_rows(QBITTORRENT, body):
        assert field in row


@pytest.mark.parametrize("model", [QbittorrentTorrent, QbittorrentFile])
def test_both_models_are_frozen(model: type[BaseModel]) -> None:
    assert model.model_config["frozen"] is True


@pytest.mark.parametrize("model", [QbittorrentTorrent, QbittorrentFile])
def test_both_models_ignore_a_key_they_never_asked_for(model: type[BaseModel]) -> None:
    """A WebUI that grows a field must not break a scan (CLAUDE.md 10.3, the untrusted-boundary rule)."""
    assert model.model_config["extra"] == "ignore"


def test_a_torrent_carries_the_fixture_values_verbatim() -> None:
    torrent = QbittorrentTorrent.model_validate(fixture_rows(QBITTORRENT, "torrents_info_completed")[0])

    assert torrent.hash == "7d3f1a2b4c5e6f708192a3b4c5d6e7f809a1b2c3"
    assert torrent.save_path == "/staging/downloads"
    assert torrent.content_path == "/staging/downloads/Some.Show.S01"
    assert torrent.progress == 1.0
    assert torrent.amount_left == 0
    assert not hasattr(torrent, "category")


def test_an_incomplete_torrent_carries_the_documented_minus_one_completion_time() -> None:
    """qBittorrent reports `completion_on: -1` for a torrent that has not completed, so the column may not
    be bounded at zero - bounding it would refuse a body the server really sends."""
    rows = fixture_rows(QBITTORRENT, "torrents_info_completed")
    # By progress rather than by index, so another fixture row cannot silently retarget this.
    partial = QbittorrentTorrent.model_validate(next(row for row in rows if row["progress"] != 1))

    assert partial.completion_on == -1
    assert partial.progress == 0.5


@pytest.mark.parametrize("missing", ["hash"])
def test_a_torrent_without_a_hash_is_refused(missing: str) -> None:
    """Everything else survives being absent; a torrent with no hash is one nothing could be asked about."""
    row = dict(fixture_rows(QBITTORRENT, "torrents_info_completed")[0])
    del row[missing]

    with pytest.raises(ValidationError):
        QbittorrentTorrent.model_validate(row)


@pytest.mark.parametrize("progress", [-0.1, 1.1])
def test_a_progress_outside_zero_to_one_is_refused(progress: float) -> None:
    row = dict(fixture_rows(QBITTORRENT, "torrents_info_completed")[0]) | {"progress": progress}

    with pytest.raises(ValidationError):
        QbittorrentTorrent.model_validate(row)


def test_a_file_carries_the_relative_path_verbatim() -> None:
    files = [QbittorrentFile.model_validate(row) for row in fixture_rows(QBITTORRENT, "torrents_files_multi")]

    assert [file.name for file in files] == [
        "Some.Show.S01/Some.Show.S01E01.1080p.WEB-DL.mkv",
        "Some.Show.S01/Some.Show.S01E02.1080p.WEB-DL.mkv",
        "Some.Show.S01/Sample/sample.mkv",
    ]


def test_the_absolute_path_is_the_save_path_joined_to_the_relative_name() -> None:
    """The one place that rule is applied, and the one place it is asserted."""
    file = QbittorrentFile.model_validate(fixture_rows(QBITTORRENT, "torrents_files_multi")[0])

    assert file.absolute_path(A_SAVE_PATH) == Path("/staging/downloads/Some.Show.S01/Some.Show.S01E01.1080p.WEB-DL.mkv")


def test_joining_the_name_to_the_content_path_instead_names_a_file_that_does_not_exist() -> None:
    """The plausible-looking alternative, shown wrong against the fixture rather than argued about.

    For a multifile torrent `content_path` is already the torrent's own root directory, so joining the
    relative name to it repeats that directory. This is the whole reason the rule lives in one named method.
    """
    torrent = QbittorrentTorrent.model_validate(fixture_rows(QBITTORRENT, "torrents_info_completed")[0])
    file = QbittorrentFile.model_validate(fixture_rows(QBITTORRENT, "torrents_files_multi")[0])

    wrong = Path(torrent.content_path) / file.name

    assert wrong == Path("/staging/downloads/Some.Show.S01/Some.Show.S01/Some.Show.S01E01.1080p.WEB-DL.mkv")
    assert wrong != file.absolute_path(Path(torrent.save_path))


def test_a_single_file_torrents_absolute_path_is_the_content_path_it_already_reported() -> None:
    """The one shape where the two constructions agree, which is exactly why the wrong one looks right."""
    torrent = QbittorrentTorrent.model_validate(fixture_rows(QBITTORRENT, "torrents_info_completed")[1])
    file = QbittorrentFile.model_validate(fixture_rows(QBITTORRENT, "torrents_files_single")[0])

    assert file.absolute_path(Path(torrent.save_path)) == Path(torrent.content_path)


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "Some.Show/../../../etc/passwd",
        "..",
        "../a.mkv",
        "Some.Show\\..\\..\\evil.mkv",
        "/etc/passwd",
        "C:/Windows/System32/config",
        "C:evil.mkv",
        "\\evil.mkv",
        "\\\\server\\share\\evil.mkv",
        "",
        ".",
        "./",
        "Show/.",
        "Show/",
        "Show\\",
        "Show//a.mkv",
        "a.mkv\x00.txt",
        "a\nb.mkv",
        "a\rb.mkv",
    ],
)
def test_a_name_that_could_walk_out_of_the_save_path_is_refused_at_the_boundary(name: str) -> None:
    """A torrent's file names are attacker-supplied in the general case, and the pipeline joins them to a
    directory it then writes into. The refusal is here, at the boundary, so `absolute_path` cannot escape.

    Three families: one that walks up, one that is ROOTED (including the Windows shape with no drive,
    which `is_absolute()` answers `False` for while `C:/staging / "\\evil.mkv"` still lands at
    `C:/evil.mkv`), and one that names a directory or carries a control character rather than a file.
    """
    with pytest.raises(ValidationError):
        QbittorrentFile.model_validate(_a_file(name=name))


@pytest.mark.parametrize(
    "name",
    [
        "a.mkv",
        "Show/a.mkv",
        "Show/Season 1/a.mkv",
        "Show/..name/a.mkv",
        "a..b.mkv",
        "Show\\a.mkv",
        "Show - S01E01 (1080p) [x265].mkv",
    ],
)
def test_an_ordinary_relative_name_is_accepted(name: str) -> None:
    file = QbittorrentFile.model_validate(_a_file(name=name))

    assert file.name == name


@pytest.mark.parametrize("name", ["a.mkv", "Show/a.mkv", "Show/Season 1/a.mkv"])
def test_no_accepted_name_can_leave_the_save_path(name: str) -> None:
    """The property the validator exists for, asserted over the shapes it lets through."""
    resolved = QbittorrentFile.model_validate(_a_file(name=name)).absolute_path(A_SAVE_PATH)

    assert PurePosixPath(resolved).is_relative_to(PurePosixPath(A_SAVE_PATH))


def test_a_file_without_an_index_is_refused() -> None:
    """`index` is the field the 2.8.2 floor exists for; a body without one is an older server."""
    row = _a_file()
    del row["index"]

    with pytest.raises(ValidationError):
        QbittorrentFile.model_validate(row)


# --- R85: which infohashes this project will act on --------------------------------------------------


@pytest.mark.parametrize("value", ["a" * 40, "0" * 40, "a" * 64, "3c9f0e1d" * 8])
def test_a_v1_or_a_v2_infohash_is_recognised(value: str) -> None:
    """Forty lowercase hex is a v1 (SHA-1) infohash; sixty-four is a v2 (SHA-256) one."""
    assert is_recognised_hash(value) is True


@pytest.mark.parametrize(
    "value",
    ["", "a" * 39, "a" * 41, "a" * 63, "a" * 65, "A" * 40, "A" * 64, "a" * 39 + "g", "a" * 40 + "\n", " " + "a" * 40],
)
def test_anything_else_is_not_recognised(value: str) -> None:
    assert is_recognised_hash(value) is False


def test_a_row_reports_whether_its_own_hash_is_recognised() -> None:
    """The predicate is exposed ONCE, so an import scan skipping a row and the client refusing to put one
    in a URL cannot disagree about what an infohash is (R85)."""
    rows = fixture_rows(QBITTORRENT, "torrents_info_completed")

    assert all(QbittorrentTorrent.model_validate(row).has_recognised_hash for row in rows)


def test_a_row_carrying_a_hash_this_project_does_not_recognise_still_validates() -> None:
    """Deliberately not a validator: one odd torrent is a row to skip, never a whole body to refuse."""
    torrent = QbittorrentTorrent.model_validate({"hash": "not-a-hash"})

    assert torrent.has_recognised_hash is False


def test_the_file_model_drops_a_key_it_never_asked_for_rather_than_refusing_it() -> None:
    """`extra="ignore"` proven by behaviour rather than by reading the config back."""
    file = QbittorrentFile.model_validate(_a_file(is_seed=True, piece_range=[0, 3], availability=1.0))

    assert not hasattr(file, "is_seed")
    assert file.name == "Some.Show.S01E01.mkv"
