"""Shared fixtures: every test runs against throwaway copies of the real workbooks."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from library_choice import a_category, library_workbooks
from tv_watchlist.config import Settings
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook import backup
from workbook_facts import WorkbookFacts


@pytest.fixture(autouse=True)
def _reset_backup_state() -> Iterator[None]:
    backup.reset()
    yield
    backup.reset()


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A disposable copy of the whole library."""
    destination = tmp_path / "library"
    destination.mkdir()
    for path in library_workbooks():
        shutil.copy2(path, destination / path.name)
    return destination


@pytest.fixture
def settings(library: Path, tmp_path: Path) -> Settings:
    return Settings(library_dir=library, backup_dir=tmp_path / "backups", heroes_dir=tmp_path / "heroes")


@pytest.fixture
def catalog(settings: Settings) -> Catalog:
    return Catalog(settings)


@pytest.fixture
def subject(library: Path) -> WorkbookFacts:
    """The default category a test writes to, chosen by shape and copied into the throwaway library."""
    return a_category()


@pytest.fixture
def subject_path(subject: WorkbookFacts, library: Path) -> Path:
    """The disposable copy of that category's workbook."""
    return subject.copied_into(library)
