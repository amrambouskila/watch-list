"""The one upstream that is allowed to be `http`, and the guard that still pins it to exactly one host.

`assert_within_base` requires https, which is right for a provider on the public internet and wrong for a
self-hosted Jellyfin at `http://jellyfin:8096`. The sibling guard relaxes the scheme and **nothing else**:
same exact-host-and-port rule, same credentials refusal, same traversal refusal. Half of this file exists to
prove the public guard did not move while the sibling was added (CLAUDE.md section 10.3, B16).
"""

from __future__ import annotations

from typing import Final

import pytest

from tv_watchlist.clients.errors import OutboundUrlError
from tv_watchlist.clients.http_guard import (
    assert_within_base,
    assert_within_configured_base,
    configured_url,
    provider_url,
)
from tv_watchlist.constants import TMDB_API_BASE_URL, TMDB_IMAGE_BASE_URL, TVDB_API_BASE_URL

# The three shapes a self-hosted Jellyfin actually takes: the host launcher path, the compose service name,
# and a box on the owner's LAN. `agent/url_guard.assert_public_http_url` rejects all three by design, which
# is why it is deliberately not the guard here.
A_LOOPBACK_BASE: Final[str] = "http://localhost:8096"
A_COMPOSE_BASE: Final[str] = "http://jellyfin:8096"
A_LAN_BASE: Final[str] = "http://192.168.1.20:8096"


# --- the relaxation, and its exact width ---------------------------------------------------------------


@pytest.mark.parametrize("base_url", [A_LOOPBACK_BASE, A_COMPOSE_BASE, A_LAN_BASE])
def test_an_http_lan_base_is_accepted_where_the_https_provider_guard_refuses_it(base_url: str) -> None:
    url = f"{base_url}/Items"

    assert_within_configured_base(url, base_url)

    with pytest.raises(OutboundUrlError):
        assert_within_base(url, base_url)


@pytest.mark.parametrize("base_url", [A_LOOPBACK_BASE, A_COMPOSE_BASE, A_LAN_BASE])
def test_the_base_itself_is_within_its_own_base(base_url: str) -> None:
    assert_within_configured_base(base_url, base_url)


def test_https_is_still_accepted_so_a_reverse_proxied_jellyfin_needs_no_second_guard() -> None:
    """The sibling ADDS http; it does not swap one mandatory scheme for another."""
    assert_within_configured_base("https://media.lan:8920/Items", "https://media.lan:8920")


@pytest.mark.parametrize(
    "url",
    [
        "http://jellyfin:8097/Items",
        "http://jellyfin/Items",
        "http://evil/Items",
        "http://jellyfin.evil:8096/Items",
        "https://jellyfin:8096/Items",
    ],
)
def test_a_different_host_port_or_scheme_is_refused(url: str) -> None:
    with pytest.raises(OutboundUrlError):
        assert_within_configured_base(url, A_COMPOSE_BASE)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@jellyfin:8096/Items",
        "http://jellyfin@evil:8096/Items",
        "http://token@jellyfin:8096/Items",
    ],
)
def test_a_url_carrying_credentials_is_refused(url: str) -> None:
    """The key travels in a header. A URL that carries one has already leaked it into every log on the path."""
    with pytest.raises(OutboundUrlError):
        assert_within_configured_base(url, A_COMPOSE_BASE)


@pytest.mark.parametrize(
    "url",
    [
        "http://jellyfin:8096/../secret",
        "http://jellyfin:8096/Items/../../secret",
        "http://jellyfin:8096/%2e%2e/secret",
        "http://jellyfin:8096/..%2Fsecret",
        "http://jellyfin:8096/%2e%2e%2Fsecret",
    ],
)
def test_a_traversal_segment_is_refused(url: str) -> None:
    """`..%2F` is one raw segment that becomes two once unquoted, so the split has to happen after decoding."""
    with pytest.raises(OutboundUrlError):
        assert_within_configured_base(url, A_COMPOSE_BASE)


@pytest.mark.parametrize("url", ["ftp://jellyfin:8096/Items", "file:///etc/passwd", "/Items", "jellyfin:8096/Items"])
def test_a_non_http_scheme_is_refused(url: str) -> None:
    with pytest.raises(OutboundUrlError):
        assert_within_configured_base(url, A_COMPOSE_BASE)


def test_a_url_outside_the_base_path_is_refused() -> None:
    with pytest.raises(OutboundUrlError):
        assert_within_configured_base("http://jellyfin:8096/other/Items", "http://jellyfin:8096/jellyfin")


def test_a_url_this_cannot_be_read_as_is_refused() -> None:
    with pytest.raises(OutboundUrlError):
        assert_within_configured_base("http://[::1:8096/Items", A_COMPOSE_BASE)


# --- the public provider guard, unchanged ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://api.themoviedb.org/3/movie/603",
        "https://api.themoviedb.org.evil/3/movie/603",
        "https://user:pass@api.themoviedb.org/3/movie/603",
        "https://api.themoviedb.org/3/..%2Fsecret",
        "ftp://api.themoviedb.org/3/movie/603",
    ],
)
def test_the_public_provider_guard_is_unchanged(url: str) -> None:
    """Adding the sibling must not have relaxed the guard both provider clients are pinned by."""
    with pytest.raises(OutboundUrlError):
        assert_within_base(url, TMDB_API_BASE_URL)


@pytest.mark.parametrize(
    ("url", "base_url"),
    [
        ("https://api.themoviedb.org/3/movie/603", TMDB_API_BASE_URL),
        ("https://image.tmdb.org/t/p/w500/abc.jpg", TMDB_IMAGE_BASE_URL),
        ("https://api4.thetvdb.com/v4/series/81797/episodes/absolute/eng", TVDB_API_BASE_URL),
    ],
)
def test_the_public_provider_guard_still_allows_what_it_always_did(url: str, base_url: str) -> None:
    assert_within_base(url, base_url)


def test_provider_url_still_refuses_an_http_base() -> None:
    """The two builders differ only in which guard they end on, and `provider_url` keeps the strict one."""
    with pytest.raises(OutboundUrlError):
        provider_url(A_COMPOSE_BASE, "Items")


# --- the builder ------------------------------------------------------------------------------------------


def test_configured_url_joins_segments_and_query_the_way_provider_url_does() -> None:
    assert configured_url(A_COMPOSE_BASE, "Shows", "abc123", "Episodes", fields="ProviderIds,Path") == (
        "http://jellyfin:8096/Shows/abc123/Episodes?fields=ProviderIds%2CPath"
    )


def test_configured_url_with_no_segments_is_the_base_itself() -> None:
    assert configured_url(A_COMPOSE_BASE) == A_COMPOSE_BASE


def test_configured_url_drops_a_none_query_value() -> None:
    assert configured_url(A_COMPOSE_BASE, "Items", limit=200, minDateLastSaved=None) == (
        "http://jellyfin:8096/Items?limit=200"
    )


@pytest.mark.parametrize(("segment", "encoded"), [("a/b", "a%2Fb"), ("x y", "x%20y"), ("?q=1", "%3Fq%3D1")])
def test_configured_url_encodes_a_segment_that_would_otherwise_change_the_path(segment: str, encoded: str) -> None:
    assert configured_url(A_COMPOSE_BASE, "Shows", segment) == f"http://jellyfin:8096/Shows/{encoded}"


def test_configured_url_refuses_a_traversal_segment_that_quoting_leaves_alone() -> None:
    """`quote` treats a dot as unreserved, so the guard on the built URL is what stops `..`."""
    with pytest.raises(OutboundUrlError):
        configured_url(A_COMPOSE_BASE, "Shows", "..")
