"""The declined scope, made mechanical: nothing in `src/` can acquire anything (ADR-015).

ADR-015 records that the owner requested an automated acquisition pipeline - a search provider, a
release-selection heuristic, magnet injection into qBittorrent and acquire endpoints - and that the
controller running the 2026-09-22 session **declined to build an automated pipeline for acquiring
unlicensed copies**. The ADR states the testable consequence in as many words: *"a source grep over `src/`
for `torrents/add`, `add_torrent`, `add_magnet`, `magnet:`, tracker names and `acquire` finds nothing -
asserted by a test whose docstring cites this ADR."* This is that test.

It is deliberately a **text** sweep rather than an import-time or surface check. A decision this shape is
broken by a line of code long before it is broken by an exported name, and a grep is the one check that
cannot be satisfied by renaming something.

**The one exemption, and it is narrow.** A forbidden token is allowed only where it sits *inside a comment
or a string* that also carries the literal `ADR-015` - because the only honest reason to write one of these
words here is to record that it is not built, and requiring the citation means the reason travels with it.
The module is tokenized to decide that, so **a forbidden token in CODE is still offending even if the same
line ends in `# ADR-015`**: a trailing comment must not be able to license the statement beside it.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path
from typing import Final

import pytest

from tv_watchlist.main import create_app

SOURCE_ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "src" / "tv_watchlist"
# The citation that exempts a comment or a docstring, because the only honest reason to write one of
# these words in this repository is to record that it is not built.
THE_CITATION: Final[str] = "ADR-015"
# Every token the ADR names, plus the tracker and indexer names the phase plan adds. Lower-case; the
# sweep folds case, so `Torrentio` and `TORRENTIO` are caught by the same entry.
FORBIDDEN: Final[tuple[str, ...]] = (
    "torrents/add",
    "add_torrent",
    "add_magnet",
    "magnet:",
    "torrentio",
    "jackett",
    "nyaa",
    "rarbg",
    "1337x",
)
# The mutating half of the WebUI's torrent API. A literal token check alone would miss these, because
# this project builds every path from SEGMENTS - `("torrents", "add")` never spells `torrents/add` - and
# because the client is read-only for a wider reason than "it does not add": it does not command the
# WebUI at all. Both spellings are matched, so neither form of the idiom can slip through.
_MUTATING: Final[str] = "add|delete|pause|resume|setLocation|setCategory|rename|recheck|reannounce"
SEGMENT_IDIOMS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf"torrents/(?:{_MUTATING})\b", re.IGNORECASE),
    re.compile(rf"""["']torrents["']\s*,\s*["'](?:{_MUTATING})["']""", re.IGNORECASE),
)
_ACQUIRE: Final[str] = "acquire"


def _python_sources(root: Path) -> list[Path]:
    """Every module under `root`, so a file added later is swept without this list being edited."""
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _citing_spans(source: str) -> dict[int, list[tuple[int, int]]]:
    """Per line number, the column span of every COMMENT or STRING token that cites the ADR.

    Tokenizing is what makes the exemption honest: a comment and a docstring are prose, and prose is the
    only place one of these words belongs. Anything the tokenizer calls code is offending whatever else
    shares its line. A module that will not tokenize exempts nothing, which is the safe direction.
    """
    spans: dict[int, list[tuple[int, int]]] = {}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return spans
    lines = source.splitlines()
    for token in tokens:
        if token.type not in {tokenize.COMMENT, tokenize.STRING} or THE_CITATION not in token.string:
            continue
        (first, start_column), (last, end_column) = token.start, token.end
        for number in range(first, last + 1):
            width = len(lines[number - 1]) if number - 1 < len(lines) else 0
            begins = start_column if number == first else 0
            ends = end_column if number == last else width
            spans.setdefault(number, []).append((begins, ends))
    return spans


def _exempt(spans: list[tuple[int, int]], start: int, length: int) -> bool:
    """Whether an occurrence at `start` lies wholly inside one citing comment or string on that line."""
    return any(begins <= start and start + length <= ends for begins, ends in spans)


def _offending_lines(token: str, *, root: Path = SOURCE_ROOT) -> list[str]:
    """Every line naming `token` outside a citing comment or string, as `path:line: text`."""
    found: list[str] = []
    for path in _python_sources(root):
        source = path.read_text(encoding="utf-8")
        spans = _citing_spans(source)
        for number, line in enumerate(source.splitlines(), start=1):
            lowered = line.lower()
            start = lowered.find(token)
            while start != -1:
                if not _exempt(spans.get(number, []), start, len(token)):
                    found.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
                    break
                start = lowered.find(token, start + 1)
    return found


def _offending_matches(pattern: re.Pattern[str], *, root: Path = SOURCE_ROOT) -> list[str]:
    """The same sweep for one regex idiom rather than one literal token."""
    found: list[str] = []
    for path in _python_sources(root):
        source = path.read_text(encoding="utf-8")
        spans = _citing_spans(source)
        for number, line in enumerate(source.splitlines(), start=1):
            for match in pattern.finditer(line):
                if not _exempt(spans.get(number, []), match.start(), len(match.group())):
                    found.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
                    break
    return found


def test_there_is_source_to_sweep() -> None:
    """A sweep over an empty tree passes for the wrong reason, so the tree is checked first."""
    sources = _python_sources(SOURCE_ROOT)

    assert len(sources) > 100
    assert SOURCE_ROOT / "clients" / "qbittorrent_client.py" in sources


@pytest.mark.parametrize("token", FORBIDDEN)
def test_no_module_carries_an_acquisition_token(token: str) -> None:
    """ADR-015: no search provider, no release-selection heuristic, no acquire route, and a qBittorrent
    client that carries no add-torrent and no add-magnet method."""
    offending = _offending_lines(token)

    assert offending == [], f"ADR-015 forbids `{token}`; found:\n" + "\n".join(offending)


@pytest.mark.parametrize("pattern", SEGMENT_IDIOMS, ids=lambda pattern: pattern.pattern[:24])
def test_no_module_commands_the_webui_through_a_mutating_endpoint(pattern: re.Pattern[str]) -> None:
    """The client reads. It does not add, delete, pause, resume, move or rename anything (ADR-015)."""
    offending = _offending_matches(pattern)

    assert offending == [], "ADR-015 forbids this idiom; found:\n" + "\n".join(offending)


def test_no_route_path_names_acquire() -> None:
    """R86: the ADR names acquire ROUTES, so the routes are read rather than the source swept.

    A text sweep for `acquire` cannot be used - `TokenBucket.acquire()` is an ordinary method in
    `clients/rate_limiter.py` - so this asks the app what it actually serves.
    """
    paths = create_app().openapi()["paths"]

    assert paths
    assert [path for path in paths if _ACQUIRE in path.lower()] == []


def test_the_sweep_catches_a_bare_token_and_a_trailing_citation_but_not_a_citing_comment(
    tmp_path: Path,
) -> None:
    """The guard's own guard, on a throwaway tree - a sweep that matches nothing proves nothing.

    Three shapes, because the rule has three halves: a forbidden token alone is caught; the same token in
    CODE on a line whose trailing comment cites the ADR is still caught (the bypass this test exists to
    close); and the token inside a comment that cites the ADR is exempt.
    """
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "bare.py").write_text('LINK = "magnet:?xt=urn:btih:1"\n')
    (root / "trailing.py").write_text('LINK = "magnet:?xt=urn:btih:1"  # allowed by ADR-015?\n')
    (root / "citing.py").write_text("# A magnet: link is never built here - ADR-015 declined it.\n")

    offending = _offending_lines("magnet:", root=root)

    assert sorted(line.split(":")[0] for line in offending) == ["bare.py", "trailing.py"]


def test_the_idiom_sweep_catches_both_spellings_and_exempts_a_citing_comment(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "slashed.py").write_text('PATH = "/api/v2/torrents/delete"\n')
    (root / "segments.py").write_text('SEGMENTS = ("torrents", "pause")\n')
    (root / "citing.py").write_text('# No "torrents", "resume" call is built here - ADR-015.\n')

    offending = [line for pattern in SEGMENT_IDIOMS for line in _offending_matches(pattern, root=root)]

    assert sorted(line.split(":")[0] for line in offending) == ["segments.py", "slashed.py"]


def test_a_module_that_will_not_tokenize_exempts_nothing(tmp_path: Path) -> None:
    """The safe direction: a file the tokenizer chokes on gets no exemption rather than a blanket one."""
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "broken.py").write_text('# ADR-015\ndef (:\n    LINK = "magnet:x"\n')

    assert _offending_lines("magnet:", root=root)
