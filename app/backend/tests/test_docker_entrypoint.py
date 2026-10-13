from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Final

import pytest

BACKEND_DIR: Final[Path] = Path(__file__).resolve().parents[1]
ENTRYPOINT_PATH: Final[Path] = BACKEND_DIR / "docker-entrypoint.sh"
DOCKERFILE_PATH: Final[Path] = BACKEND_DIR / "Dockerfile"
DOCKERIGNORE_PATH: Final[Path] = BACKEND_DIR / ".dockerignore"


def entrypoint_text() -> str:
    return ENTRYPOINT_PATH.read_bytes().decode("utf-8")


def test_entrypoint_exists() -> None:
    assert ENTRYPOINT_PATH.is_file()


def test_entrypoint_checks_out_with_lf_endings() -> None:
    # .gitattributes pins *.sh to eol=lf; a CRLF checkout breaks the shebang with "bad interpreter: /bin/sh^M".
    assert b"\r" not in ENTRYPOINT_PATH.read_bytes()


def test_entrypoint_starts_with_a_posix_shebang() -> None:
    assert entrypoint_text().startswith("#!/bin/sh\n")


def test_entrypoint_aborts_on_the_first_failure() -> None:
    assert "set -eu" in entrypoint_text()


def test_entrypoint_migrates_before_it_serves() -> None:
    text = entrypoint_text()
    assert text.index("alembic upgrade head") < text.index("exec uvicorn")


def test_entrypoint_execs_uvicorn_so_it_receives_sigterm() -> None:
    assert "exec uvicorn tv_watchlist.main:app --host 0.0.0.0 --port 8284" in entrypoint_text()


def test_dockerfile_cmd_is_the_entrypoint_in_json_array_form() -> None:
    assert '\nCMD ["/srv/app/backend/docker-entrypoint.sh"]\n' in DOCKERFILE_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "instruction",
    [
        "COPY alembic.ini ./alembic.ini",
        "COPY alembic ./alembic",
        "COPY data ./data",
        "COPY docker-entrypoint.sh ./docker-entrypoint.sh",
    ],
)
def test_dockerfile_carries_what_the_entrypoint_needs(instruction: str) -> None:
    # data/ holds franchise_prefixes.json, which the resolver loads at runtime and refuses to run without.
    assert instruction in DOCKERFILE_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["alembic", "data", "docker-entrypoint.sh", "alembic.ini"])
def test_dockerignore_does_not_name_the_build_inputs(path: str) -> None:
    assert path not in _ignore_patterns()


@pytest.mark.parametrize(
    "path",
    [
        "alembic.ini",
        "alembic/",
        "alembic/versions/0001_phase_1_schema.py",
        "data/franchise_prefixes.json",
        "docker-entrypoint.sh",
    ],
)
def test_no_dockerignore_pattern_matches_a_build_input(path: str) -> None:
    # An exact-string check misses a glob: `alembic*` or `*.ini` would exclude a file nothing names, and the
    # failure surfaces only as a missing file inside the image.
    assert _excluding_pattern(path) is None


def _ignore_patterns() -> list[str]:
    """Every exclusion pattern in .dockerignore, trailing slash stripped. Negations re-include, so they are
    not exclusions and are skipped."""
    patterns: list[str] = []
    for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        patterns.append(stripped.rstrip("/"))
    return patterns


def _excluding_pattern(path: str) -> str | None:
    """The first pattern that would drop `path` from the build context, directly or by excluding a directory
    above it, or None when nothing does."""
    parts = path.rstrip("/").split("/")
    candidates = ["/".join(parts[: depth + 1]) for depth in range(len(parts))]
    for pattern in _ignore_patterns():
        for candidate in candidates:
            if fnmatch(candidate, pattern):
                return pattern
    return None
