"""Outbound URLs never leave the constant base, and no input is ever interpolated into one."""

from __future__ import annotations

import pytest

from tv_watchlist.clients.errors import OutboundUrlError
from tv_watchlist.clients.http_guard import assert_within_base, provider_url
from tv_watchlist.constants import TMDB_API_BASE_URL, TMDB_IMAGE_BASE_URL, TVDB_API_BASE_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://api.themoviedb.org.evil/3/movie/603",
        "https://evil.example/3/movie/603",
        "http://api.themoviedb.org/3/movie/603",
        "https://api.themoviedb.org/3/../secret",
        "https://api.themoviedb.org/3/%2e%2e/secret",
        "https://api.themoviedb.org/3/..%2Fsecret",
        "https://api.themoviedb.org/3/%2e%2e%2Fsecret",
        "https://api.themoviedb.org/4/movie/603",
        "https://api.themoviedb.org/30/movie/603",
        "https://api.themoviedb.org:8443/3/movie/603",
        "https://api.themoviedb.org@evil.example/3/movie/603",
        "https://user:pass@api.themoviedb.org/3/movie/603",
        "ftp://api.themoviedb.org/3/movie/603",
        "https://[::1/3/movie/603",
        "/3/movie/603",
    ],
)
def test_a_url_off_the_constant_base_is_refused(url: str) -> None:
    with pytest.raises(OutboundUrlError):
        assert_within_base(url, TMDB_API_BASE_URL)


@pytest.mark.parametrize(
    ("url", "base_url"),
    [
        (TMDB_API_BASE_URL, TMDB_API_BASE_URL),
        ("https://api.themoviedb.org/3/movie/603", TMDB_API_BASE_URL),
        ("https://api.themoviedb.org/3/search/tv?query=one%20piece", TMDB_API_BASE_URL),
        (TMDB_IMAGE_BASE_URL, TMDB_IMAGE_BASE_URL),
        ("https://image.tmdb.org/t/p/w500/abc.jpg", TMDB_IMAGE_BASE_URL),
        ("https://api4.thetvdb.com/v4/series/81797/episodes/absolute/eng", TVDB_API_BASE_URL),
    ],
)
def test_a_url_on_the_constant_base_is_allowed(url: str, base_url: str) -> None:
    assert_within_base(url, base_url)


def test_provider_url_encodes_every_segment_and_never_interpolates() -> None:
    built = provider_url(TMDB_API_BASE_URL, "search", "tv", query="a/b?c", page=None)
    assert built == "https://api.themoviedb.org/3/search/tv?query=a%2Fb%3Fc"


def test_provider_url_leaves_an_int_id_alone_and_keeps_an_int_query_value() -> None:
    assert provider_url(TMDB_API_BASE_URL, "tv", 37854, "season", 2, page=3) == (
        "https://api.themoviedb.org/3/tv/37854/season/2?page=3"
    )


@pytest.mark.parametrize(
    ("segment", "encoded"),
    [("a/b", "a%2Fb"), ("one piece", "one%20piece"), ("?x=1", "%3Fx%3D1"), ("a#b", "a%23b")],
)
def test_provider_url_encodes_a_string_segment_that_would_otherwise_change_the_path(segment: str, encoded: str) -> None:
    assert provider_url(TMDB_API_BASE_URL, "search", segment) == f"https://api.themoviedb.org/3/search/{encoded}"


def test_provider_url_refuses_a_traversal_segment_that_quoting_leaves_alone() -> None:
    """`quote` treats a dot as unreserved, so the guard on the built URL is what stops `..`."""
    with pytest.raises(OutboundUrlError):
        provider_url(TMDB_API_BASE_URL, "search", "..")


def test_provider_url_joins_a_base_that_already_ends_in_a_slash_without_doubling_it() -> None:
    assert provider_url(TMDB_IMAGE_BASE_URL, "w500", "abc.jpg") == "https://image.tmdb.org/t/p/w500/abc.jpg"


def test_provider_url_with_no_segments_is_the_base_itself() -> None:
    assert provider_url(TVDB_API_BASE_URL) == TVDB_API_BASE_URL
