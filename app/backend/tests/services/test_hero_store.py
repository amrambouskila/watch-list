"""The write path for artwork: the model names a URL, the app downloads, judges and writes."""

from __future__ import annotations

import asyncio
import gzip
import shutil
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from mock_responder import MockResponder
from sample_images import GIF89, HTML_PAGE, JPEG, PNG, SVG_DOCUMENT, WEBP

from library_choice import a_category, another_category
from tv_watchlist.agent.errors import BlockedUrlError, HeroDownloadError, UnsafeHeroPathError, UnsupportedImageError
from tv_watchlist.config import Settings
from tv_watchlist.constants import HERO_ATTRIBUTION_FILENAME, HERO_SUFFIXES, MAX_HERO_BYTES
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.hero_candidate import HeroCandidate
from tv_watchlist.services import hero_backup
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.hero_store import HeroStore
from tv_watchlist.workbook.errors import CategoryNotFoundError

CURATED = Path(__file__).resolve().parents[3] / "heroes" / HERO_ATTRIBUTION_FILENAME
# Whichever category the library offers first by shape; the store only ever sees its id.
CATEGORY = a_category().category_id
CATEGORY_NAME = a_category().stem
SOURCE_FILE = "Series logo.svg"
CREDIT_PAGE = "https://commons.wikimedia.org/wiki/File:Series_logo.svg"
PUBLIC_IMAGE_URL = "https://93.184.216.34/wikipedia/commons/6/6c/Series_logo.png"
CANDIDATE = HeroCandidate(
    url=PUBLIC_IMAGE_URL,
    source_file=SOURCE_FILE,
    licence="Public domain",
    page=CREDIT_PAGE,
    description="The series logotype on transparency.",
)
CREDITED_ROW = f"| {CATEGORY_NAME} | {SOURCE_FILE} | Public domain | {CREDIT_PAGE} |"


def a_store(catalog: Catalog, settings: Settings, *responses: httpx.Response) -> tuple[HeroStore, MockResponder]:
    """A store whose downloads are answered from canned bytes and never leave the machine."""
    responder = MockResponder(*responses)
    return HeroStore(catalog, settings, transport=responder.transport), responder


def hero_files(settings: Settings) -> list[str]:
    """Every file in the heroes folder named after the category under test."""
    return sorted(path.name for path in settings.heroes_dir.glob(f"{CATEGORY}.*"))


def rows_of(path: Path) -> list[str]:
    """Every table row in a credit file."""
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("|")]


def a_credit_table(settings: Settings) -> Path:
    """A throwaway copy of the curated credit table, in the heroes folder the store writes to."""
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    table = settings.heroes_dir / HERO_ATTRIBUTION_FILENAME
    shutil.copy2(CURATED, table)
    return table


@pytest.mark.parametrize(
    ("data", "expected"),
    [(PNG, f"{CATEGORY}.png"), (JPEG, f"{CATEGORY}.jpg"), (GIF89, f"{CATEGORY}.gif"), (WEBP, f"{CATEGORY}.webp")],
)
async def test_each_accepted_raster_format_is_written_under_the_category_id(
    catalog: Catalog, settings: Settings, data: bytes, expected: str
) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=data))

    await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == [expected]
    assert (settings.heroes_dir / expected).read_bytes() == data


async def test_the_suffix_comes_from_the_bytes_not_from_the_url_that_served_them(
    catalog: Catalog, settings: Settings
) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=GIF89))

    await store.save(CATEGORY, CANDIDATE)

    assert PUBLIC_IMAGE_URL.endswith(".png")
    assert hero_files(settings) == [f"{CATEGORY}.gif"]


async def test_an_svg_is_refused_outright_because_it_is_scriptable_xml(catalog: Catalog, settings: Settings) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=SVG_DOCUMENT))

    with pytest.raises(UnsupportedImageError):
        await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == []


async def test_bytes_matching_no_accepted_format_are_refused_even_when_the_url_says_png(
    catalog: Catalog, settings: Settings
) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=HTML_PAGE))

    with pytest.raises(UnsupportedImageError):
        await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == []


async def test_a_download_past_the_byte_cap_is_refused(catalog: Catalog, settings: Settings) -> None:
    oversized = PNG + b"\x00" * MAX_HERO_BYTES
    store, _ = a_store(catalog, settings, httpx.Response(200, content=oversized))

    with pytest.raises(HeroDownloadError, match=str(MAX_HERO_BYTES)):
        await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == []


async def test_a_response_that_is_not_a_success_is_refused(catalog: Catalog, settings: Settings) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(404, content=b""))

    with pytest.raises(HeroDownloadError):
        await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == []


async def test_a_transport_failure_is_refused_rather_than_surfacing_as_an_httpx_error(
    catalog: Catalog, settings: Settings
) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    store = HeroStore(catalog, settings, transport=httpx.MockTransport(explode))

    with pytest.raises(HeroDownloadError):
        await store.save(CATEGORY, CANDIDATE)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/logo.png",
        "http://[::1]/logo.png",
        "http://[::ffff:127.0.0.1]/logo.png",
        "http://10.0.0.5/logo.png",
        "http://172.16.0.1/logo.png",
        "http://192.168.1.10/logo.png",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/logo.png",
    ],
)
async def test_an_address_that_is_not_publicly_routable_is_refused_before_anything_is_fetched(
    catalog: Catalog, settings: Settings, url: str
) -> None:
    store, responder = a_store(catalog, settings, httpx.Response(200, content=PNG))

    with pytest.raises(BlockedUrlError):
        await store.save(CATEGORY, CANDIDATE.model_copy(update={"url": url}))

    assert responder.requested == []
    assert hero_files(settings) == []


async def test_a_scheme_that_is_not_http_is_refused_by_the_store_and_not_only_by_the_model(
    catalog: Catalog, settings: Settings
) -> None:
    store, responder = a_store(catalog, settings, httpx.Response(200, content=PNG))
    smuggled = CANDIDATE.model_copy(update={"url": "file:///C:/Windows/win.ini"})

    with pytest.raises(BlockedUrlError):
        await store.save(CATEGORY, smuggled)

    assert responder.requested == []


@pytest.mark.parametrize(
    "category_id",
    [
        "no-such-category",
        "../../evil",
        "..\..\evil",
        "C:/Windows/Temp/evil",
        f"{CATEGORY}/../../evil",
        f"{CATEGORY}.png",
        "CON",
        "a" * 300,
    ],
)
async def test_a_category_the_library_does_not_hold_is_refused_before_anything_is_fetched(
    catalog: Catalog, settings: Settings, category_id: str
) -> None:
    store, responder = a_store(catalog, settings, httpx.Response(200, content=PNG))

    with pytest.raises(CategoryNotFoundError):
        await store.save(category_id, CANDIDATE)

    assert responder.requested == []
    assert not settings.heroes_dir.exists()


async def test_a_category_id_that_would_escape_the_heroes_folder_is_refused(
    catalog: Catalog, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    forged = (await catalog.detail(CATEGORY)).model_copy(update={"id": "../../escaped"})

    async def forged_detail(wanted_id: str) -> CategoryDetail:
        return forged

    monkeypatch.setattr(catalog, "detail", forged_detail)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG))

    with pytest.raises(UnsafeHeroPathError):
        await store.save(CATEGORY, CANDIDATE)

    assert not (settings.heroes_dir.parent.parent / "escaped.png").exists()


async def test_a_hero_of_a_different_extension_is_replaced_rather_than_left_alongside_the_new_one(
    catalog: Catalog, settings: Settings
) -> None:
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    stale = settings.heroes_dir / f"{CATEGORY}.jpeg"
    stale.write_bytes(JPEG)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG))

    await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == [f"{CATEGORY}.png"]
    assert not stale.exists()


async def test_every_suffix_a_card_looks_for_is_cleared_so_the_winner_never_depends_on_their_order(
    catalog: Catalog, settings: Settings
) -> None:
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    for suffix in HERO_SUFFIXES:
        (settings.heroes_dir / f"{CATEGORY}{suffix}").write_bytes(b"stale")
    store, _ = a_store(catalog, settings, httpx.Response(200, content=WEBP))

    await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == [f"{CATEGORY}.webp"]


async def test_the_credit_table_gains_exactly_one_row_and_keeps_every_curated_one(
    catalog: Catalog, settings: Settings
) -> None:
    table = a_credit_table(settings)
    before = rows_of(table)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG))

    await store.save(CATEGORY, CANDIDATE)

    after = rows_of(table)
    assert after[: len(before)] == before
    assert after[-1] == CREDITED_ROW
    assert len(after) == len(before) + 1


async def test_a_refused_image_credits_nothing(catalog: Catalog, settings: Settings) -> None:
    table = a_credit_table(settings)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=SVG_DOCUMENT))

    with pytest.raises(UnsupportedImageError):
        await store.save(CATEGORY, CANDIDATE)

    assert rows_of(table) == rows_of(CURATED)


async def test_the_category_it_returns_already_points_at_the_image_it_just_wrote(
    catalog: Catalog, settings: Settings
) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG))

    detail = await store.save(CATEGORY, CANDIDATE)

    assert detail.hero_url is not None
    assert detail.hero_url.split("?")[0] == f"/heroes/{CATEGORY}.png"


async def test_a_url_the_downloader_itself_refuses_is_reported_as_a_download_failure(
    catalog: Catalog, settings: Settings
) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG))
    unusable = CANDIDATE.model_copy(update={"url": f"{PUBLIC_IMAGE_URL}{chr(10)}X-Injected: 1"})

    with pytest.raises(HeroDownloadError):
        await store.save(CATEGORY, unusable)

    assert hero_files(settings) == []


async def test_the_artwork_a_pick_replaces_is_kept_where_it_can_be_recovered(
    catalog: Catalog, settings: Settings
) -> None:
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    replaced = b"the hand-recoloured mark that cannot be made again"
    (settings.heroes_dir / f"{CATEGORY}.png").write_bytes(replaced)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=JPEG))

    await store.save(CATEGORY, CANDIDATE)

    kept = [path for path in settings.backup_dir.rglob("*") if path.is_file() and path.read_bytes() == replaced]
    assert len(kept) == 1
    assert kept[0].name.startswith(CATEGORY)
    assert kept[0].suffix == ".png"


async def test_a_refused_image_leaves_the_artwork_it_would_have_replaced_exactly_where_it_was(
    catalog: Catalog, settings: Settings
) -> None:
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    standing = settings.heroes_dir / f"{CATEGORY}.png"
    standing.write_bytes(PNG)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=SVG_DOCUMENT))

    with pytest.raises(UnsupportedImageError):
        await store.save(CATEGORY, CANDIDATE)

    assert standing.read_bytes() == PNG
    assert not settings.backup_dir.exists()


REDIRECT_STATUSES = [301, 302, 303, 307, 308]
STREAM_CHUNK = 1_000_000
CHUNKS_OFFERED = 40


@pytest.mark.parametrize("status", REDIRECT_STATUSES)
async def test_a_redirect_is_reported_as_a_failure_rather_than_followed_where_it_points(
    catalog: Catalog, settings: Settings, status: int
) -> None:
    onwards = httpx.Response(status, headers={"location": "http://127.0.0.1:8284/api/categories"})
    store, responder = a_store(catalog, settings, onwards, httpx.Response(200, content=PNG))

    with pytest.raises(HeroDownloadError):
        await store.save(CATEGORY, CANDIDATE)

    assert responder.requested == [PUBLIC_IMAGE_URL]
    assert hero_files(settings) == []


async def test_a_stream_past_the_cap_is_cut_off_rather_than_read_to_the_end(
    catalog: Catalog, settings: Settings
) -> None:
    served: list[int] = []

    async def flood() -> AsyncIterator[bytes]:
        for index in range(CHUNKS_OFFERED):
            served.append(index)
            yield b"\x00" * STREAM_CHUNK

    store, _ = a_store(catalog, settings, httpx.Response(200, content=flood()))

    with pytest.raises(HeroDownloadError, match=str(MAX_HERO_BYTES)):
        await store.save(CATEGORY, CANDIDATE)

    assert len(served) <= MAX_HERO_BYTES // STREAM_CHUNK + 1
    assert hero_files(settings) == []


async def test_a_compressed_body_is_capped_by_what_it_expands_to(catalog: Catalog, settings: Settings) -> None:
    bomb = gzip.compress(PNG + b"\x00" * (MAX_HERO_BYTES * 25))
    served = httpx.Response(200, content=bomb, headers={"Content-Encoding": "gzip"})
    store, _ = a_store(catalog, settings, served)

    assert len(bomb) < MAX_HERO_BYTES

    with pytest.raises(HeroDownloadError, match=str(MAX_HERO_BYTES)):
        await store.save(CATEGORY, CANDIDATE)

    assert hero_files(settings) == []


# Long enough that a second thread genuinely gets in when nothing keeps it out, short enough that
# the guarded run pays it only once.
OVERLAP_WINDOW_SECONDS = 0.25
BOTH_PICKS = 2
# strftime passes text holding no % directive through, so both picks of a test file under one stamp.
ONE_SECOND = "one-second"


def a_second_credit_table_row(settings: Settings, category_name: str) -> list[str]:
    """Every row of the credit table naming one category."""
    table = settings.heroes_dir / HERO_ATTRIBUTION_FILENAME
    return [line for line in rows_of(table) if line.startswith(f"| {category_name} |")]


async def test_a_re_pick_replaces_this_category_s_credit_rather_than_adding_a_second(
    catalog: Catalog, settings: Settings
) -> None:
    a_credit_table(settings)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG), httpx.Response(200, content=JPEG))
    replacement = CANDIDATE.model_copy(update={"source_file": "A better mark.png"})

    await store.save(CATEGORY, CANDIDATE)
    await store.save(CATEGORY, replacement)

    credited = a_second_credit_table_row(settings, CATEGORY_NAME)
    assert len(credited) == 1
    assert "A better mark.png" in credited[0]


async def test_a_re_pick_inside_one_second_still_keeps_the_artwork_it_replaced(
    catalog: Catalog, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hero_backup, "BACKUP_TIMESTAMP_FORMAT", ONE_SECOND)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG), httpx.Response(200, content=JPEG))

    await store.save(CATEGORY, CANDIDATE)
    await store.save(CATEGORY, CANDIDATE)

    kept = sorted(path.read_bytes() for path in settings.backup_dir.iterdir() if path.is_file())
    assert kept == sorted([PNG])
    assert (settings.heroes_dir / f"{CATEGORY}.jpg").read_bytes() == JPEG


async def test_two_picks_for_one_category_never_write_at_the_same_time(
    catalog: Catalog, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_credit_table(settings)
    both_inside = threading.Barrier(BOTH_PICKS)
    overlapped = False
    write = HeroStore._write

    def observed(self: HeroStore, detail: CategoryDetail, candidate: HeroCandidate, suffix: str, data: bytes) -> None:
        nonlocal overlapped
        try:
            both_inside.wait(timeout=OVERLAP_WINDOW_SECONDS)
            overlapped = True
        except threading.BrokenBarrierError:
            pass
        write(self, detail, candidate, suffix, data)

    monkeypatch.setattr(HeroStore, "_write", observed)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG), httpx.Response(200, content=JPEG))

    await asyncio.gather(store.save(CATEGORY, CANDIDATE), store.save(CATEGORY, CANDIDATE))

    assert not overlapped


async def test_two_picks_at_once_leave_one_image_showing_and_the_other_recoverable(
    catalog: Catalog, settings: Settings
) -> None:
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG), httpx.Response(200, content=JPEG))

    await asyncio.gather(store.save(CATEGORY, CANDIDATE), store.save(CATEGORY, CANDIDATE))

    showing = [path.read_bytes() for path in settings.heroes_dir.glob(f"{CATEGORY}.*")]
    kept = [path.read_bytes() for path in settings.backup_dir.iterdir() if path.is_file()]
    assert len(showing) == 1
    assert sorted(showing + kept) == sorted([PNG, JPEG])


async def test_two_picks_at_once_credit_the_category_exactly_once(catalog: Catalog, settings: Settings) -> None:
    a_credit_table(settings)
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG), httpx.Response(200, content=JPEG))

    await asyncio.gather(store.save(CATEGORY, CANDIDATE), store.save(CATEGORY, CANDIDATE))

    assert len(a_second_credit_table_row(settings, CATEGORY_NAME)) == 1


async def test_picks_for_two_categories_at_once_leave_both_credited(catalog: Catalog, settings: Settings) -> None:
    a_credit_table(settings)
    other = another_category()
    store, _ = a_store(catalog, settings, httpx.Response(200, content=PNG), httpx.Response(200, content=JPEG))

    await asyncio.gather(store.save(CATEGORY, CANDIDATE), store.save(other.category_id, CANDIDATE))

    assert len(a_second_credit_table_row(settings, CATEGORY_NAME)) == 1
    assert len(a_second_credit_table_row(settings, other.stem)) == 1
