"""Resolve every row of every workbook against the live catalogue, and write down what happened.

The measurement the master plan's R1 asks for: "replace that estimate with a measurement". It reads the
library through the same columns the ingest reads and resolves each row with the same resolver, then
renders `docs/resolver-dry-run.md`. It is deliberately the poorer half of the ingest - no Postgres, no
cursor, no artwork, no `changes`, no season or episode ingest - because the only question it asks is how
many rows the resolver can place on its own.

Three rules it may never break, each the reason for a line below:

* It never writes a workbook. The library is copied into a temporary directory first and every read
  happens there, because `read_category` probes the Excel lock by opening the file `r+b` and the owner's
  own files are the curated data (CLAUDE.md section 0.1).
* It never writes a credential. The token is read once, through `Settings`, and handed to the client,
  which puts it in one header; nothing printed or rendered here carries it.
* It never writes to Postgres. `NullResponseCache` means every fetch is a fresh one and no cursor moves,
  so a dry run cannot make the real ingest think a payload has already been seen.

`--out` must end in `.md` - the report is Markdown, never anything else - and that is checked before a
single other thing runs: before `Settings`, before a client, before a request (Ruling 56). Without the
check, `--out Marvel.xlsx` run from the repo root would replace one of the nineteen curated workbooks
outside `Catalog._write` entirely, after however long the run itself takes.

Run it from `app/backend`:

    uv run python -m tv_watchlist.resolver.dry_run --out ../../docs/resolver-dry-run.md
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final

import httpx

from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.response_cache import NullResponseCache
from tv_watchlist.clients.tmdb_client import TmdbClient, build_tmdb_client
from tv_watchlist.clients.transport import ACCEPT_JSON, build_provider_http
from tv_watchlist.config import Settings
from tv_watchlist.constants import TMDB_API_BASE_URL, TMDB_REQUESTS_PER_SECOND
from tv_watchlist.data.enums import ResolutionState
from tv_watchlist.resolver.dry_run_report import WorkbookTally, WorstExample, render_report
from tv_watchlist.resolver.resolution_request import ResolutionRequest
from tv_watchlist.resolver.span import parse_unit
from tv_watchlist.resolver.title_resolution import TitleResolver
from tv_watchlist.workbook.curated_columns import curated_columns
from tv_watchlist.workbook.discovery import workbook_paths
from tv_watchlist.workbook.reader import read_category

# How many of a workbook's least confident rows the report shows. Five is what the gate asks for.
WORST_EXAMPLES: Final[int] = 5
# One second's worth of calls may arrive at once, exactly as `ingest.runtime` sizes its buckets. The
# sustained rate is the constant beside it and is not raised for a dry run: this is the same budget the
# real ingest spends against the same service from the same egress address.
BURST_SECONDS: Final[int] = 1
# Read-only: a `Final` dict is still mutable, and this one is handed out to every client this
# module builds.
PACKAGE_NAME: Final[str] = "tv-watchlist"
UNKNOWN_VERSION: Final[str] = "unknown version"
RESOLVER_DESCRIPTION: Final[str] = "{package} {version}, TMDB search only (no changes, seasons or artwork)"

# Ruling 56: the report is Markdown, and only Markdown - a suffix other than this one is refused before
# `Settings`, a client or a request exists, so a mistyped `--out` can never land on a root `*.xlsx`.
REPORT_SUFFIX: Final[str] = ".md"
INVALID_OUT_SUFFIX_MESSAGE: Final[str] = (
    "--out must end in {suffix} (the report is Markdown); '{path}' does not. No report was written."
)
UNCONFIGURED_MESSAGE: Final[str] = (
    "TV_TMDB_READ_ACCESS_TOKEN is unset, so there is nothing to measure. Set it in the repository root "
    ".env and run this again; no report was written."
)
NO_WORKBOOKS_MESSAGE: Final[str] = "no workbooks found in {library}; no report was written."
NEGATIVE_WORST_MESSAGE: Final[str] = "a count of rows to show cannot be negative"
MINIMUM_WORST: Final[int] = 0
PROGRESS_TEMPLATE: Final[str] = "{name}: {rows} rows, {auto} auto-resolved, {unresolved} unresolved"
WROTE_TEMPLATE: Final[str] = "wrote {path}"
COPY_DIRECTORY_PREFIX: Final[str] = "tv-dry-run-"
FIRST_POSITION: Final[int] = 1
EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1


def worst_count(value: str) -> int:
    """An argparse `type=`: how many rows to show, refused rather than reinterpreted when negative.

    Without this a `--worst -3` reaches `examples[:-3]` and quietly shows the MOST confident rows
    under a heading that promises the least confident ones.
    """
    count = int(value)
    if count < MINIMUM_WORST:
        raise argparse.ArgumentTypeError(NEGATIVE_WORST_MESSAGE)
    return count


def _bucket() -> TokenBucket:
    return TokenBucket(TMDB_REQUESTS_PER_SECOND, max(int(TMDB_REQUESTS_PER_SECOND * BURST_SECONDS), 1))


def resolver_version() -> str:
    """What produced these numbers, for the reader who finds the file a year from now."""
    try:
        installed = version(PACKAGE_NAME)
    except PackageNotFoundError:  # pragma: no cover - the package is installed in every environment we run in
        installed = UNKNOWN_VERSION
    return RESOLVER_DESCRIPTION.format(package=PACKAGE_NAME, version=installed)


async def tally_workbook(client: TmdbClient, path: Path, *, worst_n: int = WORST_EXAMPLES) -> WorkbookTally:
    """Resolve every row of one workbook and count the answers. Writes nothing, anywhere.

    `confirmed` is always 0 in a dry run - the resolver never awards it - and is counted rather than
    hard-coded so the column would still be honest if that ever changed. `unresolved` is the residual,
    so the four columns always add up.
    """
    detail = read_category(path)
    columns = curated_columns(detail.columns)
    resolver = TitleResolver(client)
    states: Counter[ResolutionState] = Counter()
    rungs: Counter[Decimal] = Counter()
    examples: list[WorstExample] = []
    for position, row in enumerate(detail.rows, start=FIRST_POSITION):
        raw_title = columns.raw_title(row)
        raw_unit = columns.raw_unit(row)
        raw_type = columns.raw_type(row)
        resolution = await resolver.resolve(
            ResolutionRequest(
                category_slug=detail.id,
                category_name=detail.name,
                raw_title=raw_title,
                raw_unit=raw_unit,
                raw_release=columns.raw_release(row),
                raw_type=raw_type,
                span=parse_unit(raw_unit, raw_type=raw_type),
            )
        )
        states[resolution.state] += 1
        rungs[resolution.confidence] += 1
        examples.append(
            WorstExample(
                position=position,
                raw_title=raw_title,
                raw_unit=raw_unit,
                confidence=resolution.confidence,
                note=resolution.note,
            )
        )
    rows = len(detail.rows)
    confirmed = states[ResolutionState.CONFIRMED]
    auto_resolved = states[ResolutionState.AUTO]
    examples.sort(key=lambda example: (example.confidence, example.position))
    return WorkbookTally(
        category_name=detail.name,
        rows=rows,
        confirmed=confirmed,
        auto_resolved=auto_resolved,
        unresolved=rows - confirmed - auto_resolved,
        worst=tuple(examples[:worst_n]),
        rungs=tuple(sorted(rungs.items())),
    )


async def _tallies(client: TmdbClient, library: Path, *, worst_n: int) -> list[WorkbookTally]:
    """Every workbook, tallied off disposable copies so the owner's own files are never opened for writing."""
    tallies: list[WorkbookTally] = []
    with tempfile.TemporaryDirectory(prefix=COPY_DIRECTORY_PREFIX) as directory:
        copies = Path(directory)
        for path in workbook_paths(library):
            shutil.copy2(path, copies / path.name)
        for path in workbook_paths(copies):
            tally = await tally_workbook(client, path, worst_n=worst_n)
            tallies.append(tally)
            print(
                PROGRESS_TEMPLATE.format(
                    name=tally.category_name,
                    rows=tally.rows,
                    auto=tally.auto_resolved,
                    unresolved=tally.unresolved,
                ),
                flush=True,
            )
    return tallies


async def _measured(settings: Settings, out: Path, *, worst_n: int, transport: httpx.AsyncBaseTransport | None) -> int:
    http = build_provider_http(TMDB_API_BASE_URL, headers=ACCEPT_JSON, transport=transport)
    try:
        # No cursor and no Postgres: a dry run must not leave the real ingest believing a payload was seen.
        client = build_tmdb_client(settings, http=http, bucket=_bucket(), cache=NullResponseCache())
        tallies = await _tallies(client, settings.library_dir, worst_n=worst_n)
    finally:
        await http.aclose()
    if not tallies:
        print(NO_WORKBOOKS_MESSAGE.format(library=settings.library_dir), file=sys.stderr)
        return EXIT_REFUSED
    out.write_text(
        render_report(tallies, measured_on=date.today(), resolver_version=resolver_version()), encoding="utf-8"
    )
    print(WROTE_TEMPLATE.format(path=out), flush=True)
    return EXIT_OK


def _parsed(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=f"{__package__}.dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="where to write the Markdown report")
    parser.add_argument(
        "--worst", type=worst_count, default=WORST_EXAMPLES, help="least confident rows shown per workbook"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Measure the whole library and write the report. `transport` is the seam a test replays through."""
    arguments = _parsed(argv)
    if arguments.out.suffix.lower() != REPORT_SUFFIX:
        # Refused here, before Settings() or a client ever exists, so this check needs no token, no
        # library and no transport - only the argument itself.
        print(INVALID_OUT_SUFFIX_MESSAGE.format(suffix=REPORT_SUFFIX, path=arguments.out), file=sys.stderr)
        return EXIT_REFUSED
    # `Settings()` rather than `get_settings()`: this is a one-shot process, and the cached singleton
    # exists for the API's dependency injection, not for a script that reads its configuration once.
    settings = Settings()
    if settings.tmdb_read_access_token is None:
        # Refuse rather than write a report of 996 unresolved rows that would read as a resolver failure.
        print(UNCONFIGURED_MESSAGE, file=sys.stderr)
        return EXIT_REFUSED
    return asyncio.run(_measured(settings, arguments.out, worst_n=arguments.worst, transport=transport))


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main())
