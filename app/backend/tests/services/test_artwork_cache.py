"""The on-disk byte cache for provider artwork: composed URLs only, and every B5 defence intact.

No test here reaches a network. The transport is an `httpx.MockTransport` serving real image bytes, and
every composed URL points at a literal address so the SSRF guard never asks a resolver anything.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import httpx
import pytest
from mock_responder import MockResponder
from sample_images import HTML_PAGE, JPEG, PNG, SVG_DOCUMENT

from tv_watchlist.config import Settings
from tv_watchlist.constants import ARTWORK_SUBDIR, MAX_ARTWORK_BYTES_PER_RUN, MAX_HERO_BYTES, TMDB_POSTER_SIZE
from tv_watchlist.data.enums import ArtworkKind, EntityKind, ExternalSource
from tv_watchlist.data.models import Artwork
from tv_watchlist.services.artwork_cache import ArtworkCache, remote_path_is_safe

# A literal address, exactly as the hero-store tests use one: `assert_public_http_url` resolves a
# hostname, and a test that resolves anything is a test that touched the network.
A_PUBLIC_IMAGE_BASE: str = "https://93.184.216.34/t/p/"
A_SAFE_REMOTE_PATH: str = "/dB4EDhre2dsC2kxYDavyKWqLQwi.jpg"

UNSAFE_REMOTE_PATHS: list[str] = [
    "/../x.jpg",
    "//h/x.jpg",
    "/a%2F.jpg",
    "/x.svg",
    "x.jpg",
    "",
    "/",
    "/x.jpg/../../y.jpg",
    "/sub/dir/x.jpg",
    "/x.jpg?y=1",
    "/x.JPG\n/y.jpg",
]


def an_artwork(remote_path: str = A_SAFE_REMOTE_PATH) -> Artwork:
    """A transient row with its id minted client-side, which is what names the cached file."""
    return Artwork(
        id=uuid.uuid4(),
        entity_kind=EntityKind.TITLE,
        kind=ArtworkKind.POSTER,
        source=ExternalSource.TMDB,
        remote_path=remote_path,
        title_id=uuid.uuid4(),
    )


def settings_for(heroes: Path) -> Settings:
    return Settings(_env_file=None, heroes_dir=heroes)


def cache_serving(heroes: Path, *responses: httpx.Response) -> tuple[ArtworkCache, MockResponder]:
    responder = MockResponder(*responses)
    return ArtworkCache(settings_for(heroes), transport=responder.transport), responder


@pytest.mark.parametrize("remote_path", UNSAFE_REMOTE_PATHS, ids=[repr(path) for path in UNSAFE_REMOTE_PATHS])
def test_an_unsafe_remote_path_is_refused(remote_path: str) -> None:
    assert remote_path_is_safe(remote_path) is False


@pytest.mark.parametrize("remote_path", ["/abc.jpg", "/a_b-c.jpeg", "/X1.png", "/x.webp", A_SAFE_REMOTE_PATH])
def test_a_tmdb_shaped_remote_path_is_allowed(remote_path: str) -> None:
    assert remote_path_is_safe(remote_path) is True


@pytest.mark.parametrize("remote_path", UNSAFE_REMOTE_PATHS, ids=[repr(path) for path in UNSAFE_REMOTE_PATHS])
async def test_an_unsafe_remote_path_is_refused_before_any_request(tmp_path: Path, remote_path: str) -> None:
    cache, responder = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG))

    cached = await cache.ensure_cached(an_artwork(remote_path), secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert cached is None
    assert responder.requested == []


async def test_cached_artwork_is_named_by_uuid_under_the_heroes_dir_never_by_remote_path(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes"
    cache, responder = cache_serving(heroes, httpx.Response(200, content=JPEG))
    artwork = an_artwork()

    cached = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert cached == heroes.resolve() / ARTWORK_SUBDIR / f"{artwork.id}.jpg"
    assert cached.is_relative_to(heroes.resolve())
    assert cached.read_bytes() == JPEG
    # The remote name never becomes a filename: a provider chooses that string, and this app does not.
    assert A_SAFE_REMOTE_PATH.lstrip("/") not in {path.name for path in cached.parent.iterdir()}
    assert responder.requested == [f"{A_PUBLIC_IMAGE_BASE}{TMDB_POSTER_SIZE}{A_SAFE_REMOTE_PATH}"]


async def test_the_url_is_composed_from_the_base_the_size_and_the_path(tmp_path: Path) -> None:
    cache, responder = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG))

    await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE, size="w342")

    assert responder.requested == [f"{A_PUBLIC_IMAGE_BASE}w342{A_SAFE_REMOTE_PATH}"]


async def test_a_local_path_is_recorded_relative_to_the_heroes_directory(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes"
    cache, _ = cache_serving(heroes, httpx.Response(200, content=PNG))
    artwork = an_artwork()

    await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    # Relative, because heroes_dir differs between the launcher path and the container, and `/heroes`
    # is served from that directory: the stored value is exactly the tail of the URL that serves it.
    assert artwork.local_path == f"{ARTWORK_SUBDIR}/{artwork.id}.png"


@pytest.mark.parametrize(("body", "expected"), [(PNG, ".png"), (JPEG, ".jpg")], ids=["png", "jpeg"])
async def test_a_raster_body_is_kept_under_the_suffix_its_own_bytes_declare(
    tmp_path: Path, body: bytes, expected: str
) -> None:
    heroes = tmp_path / "heroes"
    cache, _ = cache_serving(heroes, httpx.Response(200, content=body))
    artwork = an_artwork()

    cached = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert cached is not None
    assert cached.suffix == expected


@pytest.mark.parametrize("body", [SVG_DOCUMENT, HTML_PAGE], ids=["svg", "html"])
async def test_an_svg_body_is_refused_and_a_png_body_is_kept(tmp_path: Path, body: bytes) -> None:
    """SVG is scriptable XML, so `image_suffix` never names it and nothing reaches disk."""
    heroes = tmp_path / "heroes"
    cache, _ = cache_serving(heroes, httpx.Response(200, content=body))
    artwork = an_artwork()

    refused = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert refused is None
    assert artwork.local_path is None
    assert not (heroes / ARTWORK_SUBDIR).exists() or list((heroes / ARTWORK_SUBDIR).iterdir()) == []


async def test_the_cache_never_follows_a_redirect(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes"
    redirect = httpx.Response(302, headers={"location": "https://93.184.216.34/elsewhere.png"})
    cache, responder = cache_serving(heroes, redirect)

    assert await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE) is None
    assert len(responder.requested) == 1


async def test_a_body_past_the_cap_is_refused_not_truncated(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes"
    oversized = PNG + b"\x00" * MAX_HERO_BYTES
    cache, _ = cache_serving(heroes, httpx.Response(200, content=oversized))
    artwork = an_artwork()

    assert await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE) is None
    assert artwork.local_path is None
    assert not (heroes / ARTWORK_SUBDIR / f"{artwork.id}.png").exists()


async def test_a_refused_oversized_download_is_still_charged_to_the_run_budget(tmp_path: Path) -> None:
    """Otherwise one oversized image per title walks straight past the budget, free of charge."""
    cache, _ = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG + b"\x00" * MAX_HERO_BYTES))

    assert await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE) is None
    assert cache.spent_bytes >= MAX_HERO_BYTES


async def test_a_refusal_record_cannot_be_split_into_a_second_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Header/log injection at this boundary: a crafted `remote_path` must not forge a record."""
    crafted = "/x.jpg\nfake=1"
    cache, responder = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG))

    with caplog.at_level(logging.INFO, logger="tv_watchlist.services.artwork_cache"):
        refused = await cache.ensure_cached(an_artwork(crafted), secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert refused is None
    assert responder.requested == []
    records = [record.getMessage() for record in caplog.records]
    assert len(records) == 1
    assert "\n" not in records[0]
    assert "\r" not in records[0]
    assert "reason=unsafe-remote-path" in records[0]
    # The crafted text is still reported, so the refusal is diagnosable - just not as two records.
    assert "fake=1" in records[0]


async def test_a_refusal_from_the_host_is_data_not_an_exception(tmp_path: Path) -> None:
    cache, _ = cache_serving(tmp_path / "heroes", httpx.Response(404))

    assert await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE) is None


async def test_a_transport_failure_is_data_not_an_exception(tmp_path: Path) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    cache = ArtworkCache(settings_for(tmp_path / "heroes"), transport=httpx.MockTransport(explode))

    assert await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE) is None


@pytest.mark.parametrize(
    "base",
    ["http://93.184.216.34/t/p/", "https://93.184.216.34/t/p", "ftp://93.184.216.34/t/p/", "", "//93.184.216.34/t/p/"],
)
async def test_a_base_url_that_is_not_a_secure_directory_is_refused(tmp_path: Path, base: str) -> None:
    """`secure_base_url` arrives in a provider payload, so it is checked like any other untrusted string."""
    cache, responder = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG))

    assert await cache.ensure_cached(an_artwork(), secure_base_url=base) is None
    assert responder.requested == []


async def test_a_private_address_is_refused_by_the_ssrf_guard(tmp_path: Path) -> None:
    cache, responder = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG))

    assert await cache.ensure_cached(an_artwork(), secure_base_url="https://127.0.0.1/t/p/") is None
    assert responder.requested == []


@pytest.mark.parametrize("size", ["../w500", "w500/", "", "w500?x=1"])
async def test_a_size_that_is_not_a_bare_slug_is_refused(tmp_path: Path, size: str) -> None:
    cache, responder = cache_serving(tmp_path / "heroes", httpx.Response(200, content=PNG))

    assert await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE, size=size) is None
    assert responder.requested == []


async def test_the_run_budget_stops_the_cache_fetching_more_bytes(tmp_path: Path) -> None:
    """Resource exhaustion at the boundary: one pass has a byte budget, not just a per-image cap."""
    heroes = tmp_path / "heroes"
    cache, responder = cache_serving(heroes, httpx.Response(200, content=PNG + b"\x00" * 64))
    spent = 0
    while spent <= MAX_ARTWORK_BYTES_PER_RUN:
        cache.spend(MAX_HERO_BYTES)
        spent += MAX_HERO_BYTES

    assert cache.spent_bytes > MAX_ARTWORK_BYTES_PER_RUN
    assert await cache.ensure_cached(an_artwork(), secure_base_url=A_PUBLIC_IMAGE_BASE) is None
    assert responder.requested == []


async def test_a_local_path_pointing_at_nothing_is_fetched_again(tmp_path: Path) -> None:
    """A row can outlive its file - the owner empties the directory - and the column is not the truth."""
    heroes = tmp_path / "heroes"
    cache, responder = cache_serving(heroes, httpx.Response(200, content=PNG))
    artwork = an_artwork()
    artwork.local_path = f"{ARTWORK_SUBDIR}/{artwork.id}.png"

    cached = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert cached is not None
    assert len(responder.requested) == 1


async def test_a_local_path_that_has_left_the_heroes_directory_is_not_trusted(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    heroes = tmp_path / "heroes"
    cache, responder = cache_serving(heroes, httpx.Response(200, content=JPEG))
    artwork = an_artwork()
    artwork.local_path = f"../{outside.name}"

    cached = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert cached == heroes.resolve() / ARTWORK_SUBDIR / f"{artwork.id}.jpg"
    assert len(responder.requested) == 1


async def test_a_second_pull_of_the_same_artwork_reuses_the_file_on_disk(tmp_path: Path) -> None:
    heroes = tmp_path / "heroes"
    cache, responder = cache_serving(heroes, httpx.Response(200, content=PNG))
    artwork = an_artwork()

    first = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)
    second = await cache.ensure_cached(artwork, secure_base_url=A_PUBLIC_IMAGE_BASE)

    assert first == second
    assert len(responder.requested) == 1
