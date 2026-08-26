"""What the launcher checks before it claims the chat feature will work."""

from __future__ import annotations

from pathlib import Path

import pytest

from tv_watchlist.agent import preflight

CLAUDE = Path("C:/tools/claude/claude.EXE")
CHROMIUM = Path("C:/ms-playwright/chromium-1234/chrome.exe")


@pytest.fixture
def found(monkeypatch: pytest.MonkeyPatch) -> dict[str, Path | None]:
    """Both requirements present, until a test says otherwise."""
    present: dict[str, Path | None] = {"claude": CLAUDE, "chromium": CHROMIUM}
    monkeypatch.setattr(preflight, "installed_cli", lambda: present["claude"])
    monkeypatch.setattr(preflight, "installed_chromium", lambda: present["chromium"])
    return present


def test_a_machine_with_both_requirements_reports_nothing(found: dict[str, Path | None]) -> None:
    assert preflight.missing_requirements() == []


def test_a_missing_cli_is_reported_with_the_command_that_installs_it(found: dict[str, Path | None]) -> None:
    found["claude"] = None

    reported = preflight.missing_requirements()

    assert len(reported) == 1
    assert "claude" in reported[0]


def test_a_missing_chromium_is_reported_with_the_command_that_installs_it(found: dict[str, Path | None]) -> None:
    found["chromium"] = None

    reported = preflight.missing_requirements()

    assert len(reported) == 1
    assert "playwright install chromium" in reported[0]


def test_a_machine_missing_both_reports_both(found: dict[str, Path | None]) -> None:
    found["claude"] = None
    found["chromium"] = None

    assert len(preflight.missing_requirements()) == 2


def test_chromium_is_found_under_the_browsers_path_playwright_was_pointed_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloaded = tmp_path / "chromium-1234" / "chrome-win64"
    downloaded.mkdir(parents=True)
    (downloaded / "chrome.exe").write_bytes(b"")
    monkeypatch.setenv(preflight.BROWSERS_PATH_VARIABLE, str(tmp_path))

    assert preflight.installed_chromium() == tmp_path / "chromium-1234"


def test_an_empty_browsers_path_means_chromium_was_never_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(preflight.BROWSERS_PATH_VARIABLE, str(tmp_path))

    assert preflight.installed_chromium() is None


def test_a_chromium_directory_holding_no_executable_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "chromium-1234").mkdir()
    monkeypatch.setenv(preflight.BROWSERS_PATH_VARIABLE, str(tmp_path))

    assert preflight.installed_chromium() is None


def test_a_half_extracted_download_with_no_executable_file_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "chromium-1234" / "chrome-win64").mkdir(parents=True)
    monkeypatch.setenv(preflight.BROWSERS_PATH_VARIABLE, str(tmp_path))

    assert preflight.installed_chromium() is None
