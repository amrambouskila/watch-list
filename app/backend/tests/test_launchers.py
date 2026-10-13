from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
LAUNCHERS: Final[dict[str, Path]] = {"sh": REPO_ROOT / "run_tv.sh", "bat": REPO_ROOT / "run_tv.bat"}
# Whole, unbroken compose invocations. Neither launcher passes `-f docker-compose.yml`: both `cd` to the
# repository root first, so compose finds the file, and any `-f "$COMPOSE_FILE"` between `docker compose`
# and the subcommand would make every needle below a non-substring and this guard unsatisfiable.
REQUIRED_IN_BOTH: Final[tuple[str, ...]] = (
    "docker compose up -d postgres",
    "alembic upgrade head",
    "docker compose down --remove-orphans",
    "docker compose down --volumes --remove-orphans",
    "tv-watchlist",
    # Fix round 1. The sweep removes by image ID, so a rebuild's dangling `<repository>:<none>` layer
    # is actually removed instead of being announced and silently failing on an unresolvable tag.
    "{{.Repository}}:{{.Tag}} {{.ID}}",
    # Fix round 1. The health wait is overridable rather than a hard-coded 60.
    "TV_POSTGRES_WAIT_SECONDS",
    "[r]",
    "[k]",
    "[q]",
    "[v]",
)


@pytest.mark.parametrize("flavour", sorted(LAUNCHERS))
def test_the_launcher_offers_all_four_options_and_owns_the_compose_stack(flavour: str) -> None:
    text = LAUNCHERS[flavour].read_text(encoding="utf-8")
    for needle in REQUIRED_IN_BOTH:
        assert needle in text, f"run_tv.{flavour} lacks {needle!r}"


def test_the_batch_launcher_uses_choice_with_all_four_keys_tested_highest_first() -> None:
    text = LAUNCHERS["bat"].read_text(encoding="utf-8")
    assert "choice /c rkqv /n" in text
    # Scoped to the :menu block. The bootstrap near the top of the .bat already contains
    # `if errorlevel 1 ( echo  uv sync failed.`, which precedes `if errorlevel 4 goto volumes`; searching
    # the whole file would find that one for level 1 and report the menu as wrongly ordered.
    menu = text[text.index(":menu") :]
    order = [menu.index(f"if errorlevel {level} goto") for level in (4, 3, 2, 1)]
    assert order == sorted(order), "errorlevel branches must be tested highest-first"


def test_the_shell_launcher_keeps_lf_endings_and_a_bash_shebang() -> None:
    raw = LAUNCHERS["sh"].read_bytes()
    assert raw.startswith(b"#!/usr/bin/env bash")
    assert b"\r\n" not in raw
