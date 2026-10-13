"""The dry run itself: one workbook tallied, and the whole runnable, both without touching a network."""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest
from mock_responder import MockResponder

from library_choice import a_category
from provider_fixtures import RECORDED_TOKEN, TMDB, fixture_response, tmdb_client_for
from tv_watchlist.models.category_create import CategoryCreate
from tv_watchlist.resolver.dry_run import (
    ACCEPT_JSON,
    EXIT_REFUSED,
    INVALID_OUT_SUFFIX_MESSAGE,
    REPORT_SUFFIX,
    UNCONFIGURED_MESSAGE,
    WORST_EXAMPLES,
    main,
    tally_workbook,
    worst_count,
)
from tv_watchlist.workbook.creator import create_category

A_KNOWN_FILM: Final[str] = "Attack of the Clones"
A_KNOWN_FILM_YEAR: Final[str] = "2002"
A_TITLE_TWO_FILMS_SHARE: Final[str] = "Superman"
COVERED_COLUMNS: Final[list[str]] = ["Order", "Title", "Unit", "Release", "Type", "Watched?"]
# The same deliberate fake every recorded fixture replays; the transport answers, so it is never sent.
TMDB_CREDENTIAL_VARIABLE: Final[str] = "TV_TMDB_READ_ACCESS_TOKEN"
LIBRARY_VARIABLE: Final[str] = "TV_LIBRARY_DIR"


def a_covered_workbook(library: Path) -> Path:
    """A two-row workbook whose titles the recorded search fixtures actually answer.

    The library's own workbooks hold 4 to 202 rows apiece and the fixtures cover two titles, so a
    canned responder would answer every other row with the wrong body. The columns are the ones the
    ingest reads, written by the app's own creator, so `read_category` and `curated_columns` are
    exercised exactly as they are over a hand-built sheet.
    """
    return create_category(
        library,
        CategoryCreate(
            name="Dry Run Subject",
            columns=COVERED_COLUMNS,
            rows=[
                {"order": "1", "title": A_KNOWN_FILM, "unit": "Movie", "release": A_KNOWN_FILM_YEAR, "type": "Film"},
                {"order": "2", "title": A_TITLE_TWO_FILMS_SHARE, "unit": "Movie", "release": "", "type": "Film"},
            ],
        ),
    )


async def test_tally_workbook_with_an_unconfigured_client_counts_every_row_unresolved_and_makes_no_request(
    library: Path,
) -> None:
    subject = a_category()
    client, responder = tmdb_client_for(token=None)

    tally = await tally_workbook(client, subject.copied_into(library))

    assert tally.category_name == subject.stem
    assert tally.rows == subject.row_count
    assert tally.unresolved == tally.rows
    assert tally.auto_resolved == 0
    assert tally.confirmed == 0
    assert responder.requested == []


async def test_tally_workbook_against_fixtures_resolves_the_known_rows(library: Path) -> None:
    path = a_covered_workbook(library)
    client, _ = tmdb_client_for(
        fixture_response(TMDB, "search_movie_attack_of_the_clones"),
        fixture_response(TMDB, "search_movie_superman"),
    )

    tally = await tally_workbook(client, path)

    assert tally.rows == 2
    assert tally.auto_resolved >= 1
    # Two TMDB films are called exactly "Superman" and the row names no year, so nothing can separate
    # them: the row is left for a human and shows up among the worst.
    assert [example.raw_title for example in tally.worst if example.confidence == Decimal("0.00")] == [
        A_TITLE_TWO_FILMS_SHARE
    ]


async def test_the_tally_records_the_confidence_of_every_row_not_only_the_worst(library: Path) -> None:
    path = a_covered_workbook(library)
    client, _ = tmdb_client_for(
        fixture_response(TMDB, "search_movie_attack_of_the_clones"),
        fixture_response(TMDB, "search_movie_superman"),
    )

    tally = await tally_workbook(client, path)

    assert sum(count for _, count in tally.rungs) == tally.rows


async def test_the_worst_list_is_capped_and_ordered(library: Path) -> None:
    subject = a_category()
    client, _ = tmdb_client_for(token=None)

    tally = await tally_workbook(client, subject.copied_into(library), worst_n=2)

    assert len(tally.worst) == 2
    assert [example.position for example in tally.worst] == [1, 2]


@pytest.mark.parametrize("worst_n", [0, 1, WORST_EXAMPLES])
async def test_the_worst_list_never_exceeds_what_was_asked_for(library: Path, worst_n: int) -> None:
    subject = a_category()
    client, _ = tmdb_client_for(token=None)

    tally = await tally_workbook(client, subject.copied_into(library), worst_n=worst_n)

    assert len(tally.worst) == min(worst_n, tally.rows)


def test_main_refuses_without_a_token_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(TMDB_CREDENTIAL_VARIABLE, raising=False)
    monkeypatch.setenv(LIBRARY_VARIABLE, str(tmp_path))
    out = tmp_path / "report.md"

    code = main(["--out", str(out)])

    assert code != 0
    assert UNCONFIGURED_MESSAGE in capsys.readouterr().err
    assert not out.exists()


def test_main_writes_a_report_for_every_workbook_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    one_workbook = tmp_path / "library"
    one_workbook.mkdir()
    path = a_covered_workbook(one_workbook)
    monkeypatch.setenv(TMDB_CREDENTIAL_VARIABLE, RECORDED_TOKEN)
    monkeypatch.setenv(LIBRARY_VARIABLE, str(one_workbook))
    out = tmp_path / "report.md"
    responder = MockResponder(fixture_response(TMDB, "search_movie_superman"))

    code = main(["--out", str(out)], transport=responder.transport)

    assert code == 0
    report = out.read_text(encoding="utf-8")
    assert f"| {path.stem} | 2 |" in report
    assert report.endswith("\n")
    assert RECORDED_TOKEN not in report
    assert RECORDED_TOKEN not in capsys.readouterr().out


def test_main_leaves_the_library_it_read_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The run works on copies: the owner's own files must come back byte-identical, and unlocked."""
    one_workbook = tmp_path / "library"
    one_workbook.mkdir()
    path = a_covered_workbook(one_workbook)
    before = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.setenv(TMDB_CREDENTIAL_VARIABLE, RECORDED_TOKEN)
    monkeypatch.setenv(LIBRARY_VARIABLE, str(one_workbook))
    responder = MockResponder(fixture_response(TMDB, "search_movie_superman"))

    main(["--out", str(tmp_path / "report.md")], transport=responder.transport)

    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_main_refuses_an_empty_library_rather_than_writing_an_empty_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "library"
    empty.mkdir()
    monkeypatch.setenv(TMDB_CREDENTIAL_VARIABLE, RECORDED_TOKEN)
    monkeypatch.setenv(LIBRARY_VARIABLE, str(empty))
    out = tmp_path / "report.md"

    code = main(["--out", str(out)])

    assert code != 0
    assert str(empty) in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize(("given", "expected"), [("0", 0), ("1", 1), ("5", 5), ("12", 12)])
def test_worst_count_reads_a_count_of_rows(given: str, expected: int) -> None:
    assert worst_count(given) == expected


@pytest.mark.parametrize("given", ["-1", "-5"])
def test_worst_count_refuses_a_negative_rather_than_slicing_from_the_wrong_end(given: str) -> None:
    # `examples[:-3]` would silently show the MOST confident rows under the worst-confidence heading.
    with pytest.raises(argparse.ArgumentTypeError):
        worst_count(given)


def test_main_refuses_a_negative_worst_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TMDB_CREDENTIAL_VARIABLE, RECORDED_TOKEN)
    monkeypatch.setenv(LIBRARY_VARIABLE, str(tmp_path))
    out = tmp_path / "report.md"

    with pytest.raises(SystemExit) as refusal:
        main(["--out", str(out), "--worst", "-1"])

    assert refusal.value.code != 0
    assert not out.exists()


@pytest.mark.parametrize("suffix", ["report.xlsx", "Marvel.XLSX", "notes.txt"])
def test_main_refuses_a_non_markdown_out_path_before_settings_or_a_client_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], suffix: str
) -> None:
    """Ruling 56: a `--out` that is not `.md` is refused by argument handling alone.

    No TMDB token or library directory is configured for this test and none is patched - if the suffix
    check ran anywhere but first, this would either explode looking for a library or fall through to
    `UNCONFIGURED_MESSAGE` instead. Getting exactly this message, unconditionally, is the proof that
    nothing past argument parsing - not `Settings()`, not a client, not a request - ever ran.
    """
    out = tmp_path / suffix

    code = main(["--out", str(out)])

    assert code == EXIT_REFUSED
    assert INVALID_OUT_SUFFIX_MESSAGE.format(suffix=REPORT_SUFFIX, path=out) in capsys.readouterr().err
    assert not out.exists()


def test_main_accepts_a_markdown_out_path_and_moves_past_the_suffix_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The module's own documented command, `--out ../../docs/resolver-dry-run.md`, passes the check.

    No TMDB token is configured, so `main()` refuses one step later, on `UNCONFIGURED_MESSAGE` - proof
    a `.md` path clears the suffix validator without ever building a client or making a request
    (Ruling 36: the dry run itself is never executed by this suite, live or otherwise).
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    backend = repo / "app" / "backend"
    backend.mkdir(parents=True)
    monkeypatch.chdir(backend)
    monkeypatch.delenv("TV_TMDB_READ_ACCESS_TOKEN", raising=False)

    code = main(["--out", "../../docs/resolver-dry-run.md"])

    assert code == EXIT_REFUSED
    assert UNCONFIGURED_MESSAGE in capsys.readouterr().err
    assert not (repo / "docs" / "resolver-dry-run.md").exists()


def test_the_accept_header_the_clients_are_handed_cannot_be_mutated() -> None:
    """It is module state handed to every client this module builds; `Final` alone does not protect it."""
    with pytest.raises(TypeError):
        ACCEPT_JSON["Accept"] = "text/html"
