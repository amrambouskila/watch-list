"""The read-only qBittorrent client, driven entirely by hand-authored bodies. No test here opens a socket.

The fixtures under `tests/fixtures/qbittorrent/` are shaped from the WebUI API wiki page rather than
recorded from a running instance - that directory's README says why, and the second reason is the binding
one: the owner's own instance holds the owner's own download history, which may not enter a public
repository.

What this file proves: the client cannot acquire anything, the password rides in one form body and nowhere
else, the configured host is the whole allowlist, a 403 costs exactly one re-login and never a loop, an old
Web API version is refused by name rather than guessed past, and a partial torrent is dropped even when the
server lists it under `filter=completed`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import httpx
import pytest
from pydantic import SecretStr

from provider_fixtures import (
    A_CREDENTIAL_WITH_A_NEWLINE,
    A_QBITTORRENT_BASE_URL,
    A_RECORDED_QBITTORRENT_PASSWORD,
    A_RECORDED_QBITTORRENT_USER,
    A_RECORDED_SID,
    QBITTORRENT,
    H11RejectingResponder,
    RecordingResponder,
    fixture_response,
    fixture_rows,
    fixture_text_response,
    qbittorrent_client_for,
    qbittorrent_login_response,
)
from tv_watchlist.clients.errors import (
    OutboundUrlError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRefusedError,
    ProviderResponseTooLargeError,
    ProviderUnavailableError,
    QbittorrentAuthError,
    QbittorrentNotConfiguredError,
    QbittorrentUnsupportedVersionError,
)
from tv_watchlist.clients.qbittorrent_client import (
    QbittorrentClient,
    build_qbittorrent_client,
    build_qbittorrent_http,
)
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    MAX_QBITTORRENT_RESPONSE_BYTES,
    QBITTORRENT_MIN_WEBAPI_VERSION,
    UNCONFIGURED_UPSTREAM_BASE_URL,
)

LOGGER_NAME: Final[str] = "tv_watchlist.clients.qbittorrent_client"
MODULE_SOURCE: Final[str] = (
    Path(__file__).resolve().parents[2] / "src" / "tv_watchlist" / "clients" / "qbittorrent_client.py"
).read_text()

A_MULTI_FILE_HASH: Final[str] = "7d3f1a2b4c5e6f708192a3b4c5d6e7f809a1b2c3"
A_SINGLE_FILE_HASH: Final[str] = "1f2e3d4c5b6a798807162534435261708f9e0d1c"
A_V2_HASH: Final[str] = "3c9f0e1d2a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d"
A_PARTIAL_HASH: Final[str] = "0a9b8c7d6e5f40312213243546576879a0b1c2d3"
A_CHUNK: Final[int] = 1_000_000

# The four methods a caller may reach, plus the two the lifespan needs to close the pool it opened. An
# EXACT set, so a later session cannot add a fifth without this test saying so (ADR-015).
THE_WHOLE_PUBLIC_SURFACE: Final[frozenset[str]] = frozenset(
    {"configured", "closed", "webapi_version", "completed_torrents", "torrent_files", "aclose"}
)
# Every public call, by name, so one sweep drives all of them rather than three tests drifting apart.
EVERY_CALL: Final[tuple[str, ...]] = ("webapi_version", "completed_torrents", "torrent_files")


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


async def _invoke(client: QbittorrentClient, call: str) -> object:
    """Drive one public method by name, with arguments that are valid for it and nothing else."""
    if call == "webapi_version":
        return await client.webapi_version()
    if call == "completed_torrents":
        return await client.completed_torrents()
    return await client.torrent_files(A_MULTI_FILE_HASH)


async def _oversized_body() -> AsyncIterator[bytes]:
    """One byte past this client's cap, and deliberately not JSON so a parse would fail differently."""
    sent = 0
    while sent < MAX_QBITTORRENT_RESPONSE_BYTES + 1:
        step = min(A_CHUNK, MAX_QBITTORRENT_RESPONSE_BYTES + 1 - sent)
        sent += step
        yield b"<" * step


def _version(text: str) -> httpx.Response:
    """What `GET /api/v2/app/webapiVersion` answers: a bare string, not JSON."""
    return httpx.Response(200, text=text, headers={"content-type": "text/plain"})


def _unreachable_client(message: str) -> tuple[QbittorrentClient, list[httpx.Request]]:
    """A client whose transport refuses every connection, and the attempts it recorded."""
    attempts: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError(message, request=request)

    client = QbittorrentClient(
        A_QBITTORRENT_BASE_URL,
        A_RECORDED_QBITTORRENT_USER,
        SecretStr(A_RECORDED_QBITTORRENT_PASSWORD),
        http=build_qbittorrent_http(A_QBITTORRENT_BASE_URL, transport=httpx.MockTransport(refuse)),
    )
    return client, attempts


# --- it cannot acquire anything (ADR-015) -------------------------------------------------------------------


def test_the_public_surface_is_read_only() -> None:
    """ADR-015: the controller declined to build an automated acquisition pipeline, and the concrete
    consequence is that this client carries no add-torrent and no add-magnet method.

    An EXACT set rather than a `not in` check, so a method added later fails here by existing at all. The
    two beyond the brief's four are `aclose` and `closed`: the R63 lifespan close calls the first and the
    test that proves the pool was shut reads the second, exactly as the Jellyfin client's do.
    """
    public = {name for name in dir(QbittorrentClient) if not name.startswith("_")}

    assert public == set(THE_WHOLE_PUBLIC_SURFACE)


@pytest.mark.parametrize("forbidden", ["add", "magnet", "search", "download", "delete", "pause", "resume"])
def test_no_public_member_is_even_named_after_acquiring_something(forbidden: str) -> None:
    """The cheap half of the check above, kept because it catches an `add_magnet` before it is called."""
    public = {name for name in dir(QbittorrentClient) if not name.startswith("_")}

    assert not {name for name in public if forbidden in name.lower()}


@pytest.mark.parametrize("forbidden", ["torrents/add", "add_torrent", "add_magnet", "magnet:"])
def test_the_module_source_carries_no_acquisition_path(forbidden: str) -> None:
    """A private helper would not show up in `dir()`, so the source is read as well as the surface.

    `tests/test_no_acquisition_surface.py` does this repo-wide; this keeps the client's own file honest
    even if that sweep is ever narrowed.
    """
    assert forbidden not in MODULE_SOURCE.lower()


# --- the credential ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base_url", "user", "password"),
    [
        (None, A_RECORDED_QBITTORRENT_USER, A_RECORDED_QBITTORRENT_PASSWORD),
        (A_QBITTORRENT_BASE_URL, None, A_RECORDED_QBITTORRENT_PASSWORD),
        (A_QBITTORRENT_BASE_URL, A_RECORDED_QBITTORRENT_USER, None),
        (None, None, None),
    ],
)
@pytest.mark.parametrize("call", EVERY_CALL)
async def test_a_missing_credential_means_not_configured_and_no_request_is_made(
    base_url: str | None, user: str | None, password: str | None, call: str
) -> None:
    client, responder = qbittorrent_client_for(base_url=base_url, user=user, password=password)

    assert client.configured is False
    with pytest.raises(QbittorrentNotConfiguredError):
        await _invoke(client, call)

    assert responder.requested == []


async def test_the_unconfigured_refusal_is_a_provider_not_configured_error_like_every_other_clients() -> None:
    """The staging-folder arm of the scan carries on regardless, so this is a disabled feature and not a
    failure - and it is caught by the same `ProviderNotConfiguredError` every other client raises."""
    client, _ = qbittorrent_client_for(base_url=None)

    with pytest.raises(ProviderNotConfiguredError):
        await client.completed_torrents()


@pytest.mark.parametrize("call", EVERY_CALL)
async def test_every_unconfigured_refusal_carries_the_same_sentence(call: str) -> None:
    """One message whichever of the three is missing, so the wording leaks which one it was."""
    client, _ = qbittorrent_client_for(base_url=None, user=None, password=None)

    with pytest.raises(QbittorrentNotConfiguredError) as raised:
        await _invoke(client, call)

    assert str(raised.value) == (
        "TV_QBITTORRENT_URL, TV_QBITTORRENT_USER or TV_QBITTORRENT_PASSWORD is unset, so qBittorrent is disabled"
    )


@pytest.mark.parametrize(
    ("base_url", "user", "password"),
    [
        ("", A_RECORDED_QBITTORRENT_USER, A_RECORDED_QBITTORRENT_PASSWORD),
        (A_QBITTORRENT_BASE_URL, "", A_RECORDED_QBITTORRENT_PASSWORD),
        (A_QBITTORRENT_BASE_URL, A_RECORDED_QBITTORRENT_USER, ""),
    ],
)
@pytest.mark.parametrize("call", EVERY_CALL)
async def test_a_blank_credential_is_the_disabled_feature_and_not_a_value(
    base_url: str, user: str, password: str, call: str
) -> None:
    """R91: `TV_QBITTORRENT_USER=` means "I have not set this up". A login posted with a blank username
    is a real request that really fails, and the owner meets a 403 instead of a disabled arm."""
    client, responder = qbittorrent_client_for(base_url=base_url, user=user, password=password)

    assert client.configured is False
    with pytest.raises(QbittorrentNotConfiguredError):
        await _invoke(client, call)

    assert responder.requested == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"qbittorrent_url": ""},
        {"qbittorrent_user": ""},
        {"qbittorrent_password": SecretStr("")},
    ],
)
def test_settings_map_a_blank_line_to_an_unset_value(overrides: dict[str, object]) -> None:
    """The other half of R91: the blank never becomes a value in the first place, and the R80 shape
    check still runs on every non-empty base."""
    configured: dict[str, object] = {
        "qbittorrent_url": A_QBITTORRENT_BASE_URL,
        "qbittorrent_user": A_RECORDED_QBITTORRENT_USER,
        "qbittorrent_password": SecretStr(A_RECORDED_QBITTORRENT_PASSWORD),
    }

    settings = Settings(_env_file=None, **(configured | overrides))

    assert build_qbittorrent_client(settings).configured is False


async def test_a_configured_client_says_so() -> None:
    client, _ = qbittorrent_client_for()

    assert client.configured is True


async def test_login_posts_form_encoded_credentials_and_keeps_the_sid_cookie() -> None:
    """The wiki: `POST /api/v2/auth/login` takes `username` and `password`, and the response carries a
    cookie with the SID which every later authenticated call must supply."""
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    await client.completed_torrents()

    login = responder.requests[0]
    assert login.method == "POST"
    assert login.url.path == "/api/v2/auth/login"
    assert login.headers["content-type"] == "application/x-www-form-urlencoded"
    assert login.content == (
        f"username={A_RECORDED_QBITTORRENT_USER}&password={A_RECORDED_QBITTORRENT_PASSWORD}".encode()
    )
    assert responder.requests[1].headers["cookie"] == f"SID={A_RECORDED_SID}"


async def test_the_password_never_reaches_a_url() -> None:
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    await client.completed_torrents()

    assert all(A_RECORDED_QBITTORRENT_PASSWORD not in str(request.url) for request in responder.requests)
    assert all("password" not in str(request.url).lower() for request in responder.requests)


async def test_the_password_rides_in_the_login_body_and_in_no_header_at_all() -> None:
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    await client.completed_torrents()

    for request in responder.requests:
        assert all(A_RECORDED_QBITTORRENT_PASSWORD not in value for value in request.headers.values())
    assert all(request.content == b"" for request in responder.requests[1:])


async def test_the_session_logs_in_once_and_reuses_the_sid() -> None:
    """A login per call would be a login storm against a server that bans on repeated failed logins."""
    client, responder = qbittorrent_client_for(
        fixture_response(QBITTORRENT, "torrents_info_completed"),
        fixture_response(QBITTORRENT, "torrents_files_multi"),
    )

    await client.completed_torrents()
    await client.torrent_files(A_MULTI_FILE_HASH)

    logins = [request for request in responder.requests if request.url.path.endswith("/auth/login")]
    assert len(logins) == 1


async def test_every_request_carries_referer_and_origin_matching_the_base() -> None:
    """The wiki requires it: "Set `Referer` or `Origin` header to the exact same domain and port as used in
    the HTTP query `Host` header." qBittorrent enforces it as CSRF protection."""
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    await client.completed_torrents()

    assert responder.requests
    for request in responder.requests:
        assert request.headers["Referer"] == A_QBITTORRENT_BASE_URL
        assert request.headers["Origin"] == A_QBITTORRENT_BASE_URL


async def test_referer_and_origin_are_derived_from_the_base_and_never_carry_its_path() -> None:
    """An `Origin` is a scheme, a host and a port - a path in it would not match the `Host` the server sees."""
    base_url = "http://127.0.0.1:8080/qbittorrent"
    responder = RecordingResponder(qbittorrent_login_response(), fixture_text_response(QBITTORRENT, "webapi_version"))
    client, _ = qbittorrent_client_for(base_url=base_url, responder=responder)

    await client.webapi_version()

    assert responder.requests[0].headers["Origin"] == "http://127.0.0.1:8080"


# --- a 403 is one re-login and never a loop ------------------------------------------------------------------


async def test_a_403_on_a_data_call_re_authenticates_once_and_retries() -> None:
    """The documented 403 means "unauthenticated" - so the SID expired and one fresh login is the answer."""
    client, responder = qbittorrent_client_for(
        httpx.Response(403, text="Forbidden"),
        qbittorrent_login_response(),
        fixture_response(QBITTORRENT, "torrents_info_completed"),
    )

    torrents = await client.completed_torrents()

    assert len(torrents) == 3
    logins = [request for request in responder.requests if request.url.path.endswith("/auth/login")]
    assert len(logins) == 2
    data = [request for request in responder.requests if request.url.path.endswith("/torrents/info")]
    assert len(data) == 2


async def test_a_second_403_raises_auth_error_without_a_third_attempt() -> None:
    """The other documented 403 is an IP ban for repeated failed logins, and a retry loop is how a client
    earns one. Two data attempts, two logins, and then it stops."""
    client, responder = qbittorrent_client_for(
        httpx.Response(403, text="Forbidden"),
        qbittorrent_login_response(),
        httpx.Response(403, text="Forbidden"),
        httpx.Response(403, text="Forbidden"),
    )

    with pytest.raises(QbittorrentAuthError):
        await client.completed_torrents()

    data = [request for request in responder.requests if request.url.path.endswith("/torrents/info")]
    assert len(data) == 2
    logins = [request for request in responder.requests if request.url.path.endswith("/auth/login")]
    assert len(logins) == 2


async def test_a_403_on_the_login_itself_is_a_ban_and_is_not_retried() -> None:
    client, responder = qbittorrent_client_for(httpx.Response(403, text="Forbidden"), login=False, version=False)

    with pytest.raises(QbittorrentAuthError):
        await client.completed_torrents()

    assert len(responder.requests) == 1


async def test_a_login_that_does_not_answer_ok_is_refused() -> None:
    """The wiki says the successful body is `Ok.`; anything else is a server that did not authenticate us."""
    client, _ = qbittorrent_client_for(httpx.Response(200, text="Fails."), login=False, version=False)

    with pytest.raises(QbittorrentAuthError):
        await client.webapi_version()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(404, ProviderNotFoundError), (429, ProviderRefusedError), (500, ProviderUnavailableError)],
)
async def test_a_login_refused_with_anything_but_403_is_reported_as_the_status_it_is(
    status: int, expected: type[ProviderError]
) -> None:
    """A 403 on the login is the ban; every other refusal is an ordinary upstream answer and is read as one."""
    client, responder = qbittorrent_client_for(httpx.Response(status, text="no"), login=False, version=False)

    with pytest.raises(expected):
        await client.webapi_version()

    assert len(responder.requests) == 1


async def test_an_auth_error_is_a_provider_error_so_the_scan_can_catch_one_family() -> None:
    assert issubclass(QbittorrentAuthError, ProviderError)
    assert issubclass(QbittorrentNotConfiguredError, ProviderError)
    assert issubclass(QbittorrentUnsupportedVersionError, ProviderError)


# --- the version floor ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["2.0", "2.6.0", "2.8.1", "1.9.9"])
@pytest.mark.parametrize("call", ["completed_torrents", "torrent_files"])
async def test_a_webapi_version_below_the_floor_is_refused_by_name(version: str, call: str) -> None:
    """`content_path` arrived in 2.6.1 and a file's `index` in 2.8.2. Guessing that an older server carries
    them is exactly the "do not guess field names" failure this client is written to avoid."""
    client, responder = qbittorrent_client_for(_version(version), version=False)

    with pytest.raises(QbittorrentUnsupportedVersionError) as raised:
        await _invoke(client, call)

    assert version in str(raised.value)
    assert QBITTORRENT_MIN_WEBAPI_VERSION in str(raised.value)
    # The floor is a gate, not a warning: the data call is never made, so no field this server does not
    # send is ever read off a body.
    assert [request.url.path for request in responder.requests] == [
        "/api/v2/auth/login",
        "/api/v2/app/webapiVersion",
    ]


@pytest.mark.parametrize("version", ["2.8.2", "2.9", "2.11.4", "3.0.0"])
async def test_a_supported_version_passes_and_is_compared_numerically(version: str) -> None:
    """`2.11.4` is LOWER than `2.8.2` as a string, so a lexical comparison would refuse a modern server."""
    client, _ = qbittorrent_client_for(
        _version(version), fixture_response(QBITTORRENT, "torrents_info_completed"), version=False
    )

    assert len(await client.completed_torrents()) == 3


@pytest.mark.parametrize("version", ["", "banana", "2.x.1", "-1", "2..8"])
async def test_a_version_that_is_not_a_version_is_refused_rather_than_assumed_modern(version: str) -> None:
    client, _ = qbittorrent_client_for(_version(version), version=False)

    with pytest.raises(QbittorrentUnsupportedVersionError):
        await client.completed_torrents()


async def test_the_refusal_never_repeats_a_whole_oversized_version_string() -> None:
    """The version is upstream text, so it is capped and newline-stripped before it is named - a crafted
    body must not be able to end a log record or fill an exception message (CLAUDE.md 10.3)."""
    client, _ = qbittorrent_client_for(_version("9" * 400 + "\nInjected: yes"), version=False)

    with pytest.raises(QbittorrentUnsupportedVersionError) as raised:
        await client.completed_torrents()

    assert "\n" not in str(raised.value)
    assert "Injected" not in str(raised.value)


async def test_webapi_version_returns_what_the_server_said() -> None:
    client, _ = qbittorrent_client_for(fixture_text_response(QBITTORRENT, "webapi_version"), version=False)

    assert await client.webapi_version() == "2.11.4"


async def test_the_version_is_read_once_per_session_and_not_once_per_call() -> None:
    client, responder = qbittorrent_client_for(
        fixture_response(QBITTORRENT, "torrents_info_completed"),
        fixture_response(QBITTORRENT, "torrents_files_multi"),
    )

    await client.completed_torrents()
    await client.torrent_files(A_MULTI_FILE_HASH)

    probes = [request for request in responder.requests if request.url.path.endswith("/webapiVersion")]
    assert len(probes) == 1


# --- completed torrents --------------------------------------------------------------------------------------


async def test_completed_torrents_asks_for_filter_completed() -> None:
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    await client.completed_torrents()

    listing = next(request for request in responder.requests if request.url.path.endswith("/torrents/info"))
    assert listing.url.query.decode() == "filter=completed"
    assert listing.method == "GET"


async def test_completed_torrents_returns_the_documented_fields() -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    torrents = await client.completed_torrents()

    first = torrents[0]
    assert first.hash == A_MULTI_FILE_HASH
    assert first.name == "Some.Show.S01.1080p.WEB-DL"
    assert first.save_path == "/staging/downloads"
    assert first.content_path == "/staging/downloads/Some.Show.S01"
    assert first.state == "pausedUP"
    assert first.progress == 1.0
    assert first.completion_on == 1758585600
    assert first.size == 8589934592
    assert first.amount_left == 0


async def test_a_partial_torrent_is_dropped_even_if_the_server_lists_it() -> None:
    """`filter=completed` is the server's word for it; `progress` and `amount_left` are the file's own."""
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    torrents = await client.completed_torrents()

    assert [torrent.hash for torrent in torrents] == [A_MULTI_FILE_HASH, A_SINGLE_FILE_HASH, A_V2_HASH]
    assert A_PARTIAL_HASH not in {torrent.hash for torrent in torrents}


async def test_an_empty_list_is_an_empty_library_and_not_a_failure() -> None:
    client, _ = qbittorrent_client_for(httpx.Response(200, json=[]))

    assert await client.completed_torrents() == []


# --- torrent files -------------------------------------------------------------------------------------------


async def test_torrent_files_asks_for_the_hash_in_the_query() -> None:
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_multi"))

    await client.torrent_files(A_MULTI_FILE_HASH)

    contents = next(request for request in responder.requests if request.url.path.endswith("/torrents/files"))
    assert contents.url.query.decode() == f"hash={A_MULTI_FILE_HASH}"


@pytest.mark.parametrize(
    "torrent_hash",
    [
        "",
        "../../etc/passwd",
        "ZZZZ",
        "a" * 39,
        "a" * 41,
        "a" * 63,
        "a" * 65,
        "7D3F1A2B4C5E6F708192A3B4C5D6E7F809A1B2C3",
        "7d3f1a2b4c5e6f708192a3b4c5d6e7f809a1b2c3 ",
    ],
)
async def test_torrent_files_refuses_a_hash_that_is_not_forty_or_sixty_four_hex(torrent_hash: str) -> None:
    """Refused BEFORE the version probe and before the login, so nothing reaches the transport at all."""
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_multi"))

    with pytest.raises(OutboundUrlError):
        await client.torrent_files(torrent_hash)

    assert responder.requested == []


@pytest.mark.parametrize("torrent_hash", [A_MULTI_FILE_HASH, A_V2_HASH])
async def test_torrent_files_accepts_both_a_v1_and_a_v2_infohash(torrent_hash: str) -> None:
    """R85: forty lowercase hex is a v1 (SHA-1) infohash and sixty-four is a v2 (SHA-256) one, and
    qBittorrent really reports both. Refusing v2 would fail a whole import pass over one modern torrent."""
    client, responder = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_multi"))

    files = await client.torrent_files(torrent_hash)

    assert files
    contents = next(request for request in responder.requests if request.url.path.endswith("/torrents/files"))
    assert contents.url.query.decode() == f"hash={torrent_hash}"


async def test_a_listed_v2_torrent_is_returned_and_reports_a_recognised_hash() -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    torrents = await client.completed_torrents()

    v2 = next(torrent for torrent in torrents if torrent.hash == A_V2_HASH)
    assert v2.has_recognised_hash is True


async def test_a_refused_hash_is_never_repeated_back_in_the_message() -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_multi"))

    with pytest.raises(OutboundUrlError) as raised:
        await client.torrent_files("../../etc/passwd")

    assert "passwd" not in str(raised.value)


async def test_torrent_files_returns_every_file_the_server_listed() -> None:
    """This client filters nothing. What is small enough to be a sample is the import scan's judgement
    (`MEDIA_IMPORT_MIN_BYTES`), and a filter here would hide files from a pass that can explain them."""
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_multi"))

    files = await client.torrent_files(A_MULTI_FILE_HASH)

    assert [file.index for file in files] == [0, 1, 2]
    assert files[2].name.endswith("sample.mkv")


async def test_torrent_files_carries_the_relative_path_verbatim() -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_multi"))

    files = await client.torrent_files(A_MULTI_FILE_HASH)

    assert files[0].name == "Some.Show.S01/Some.Show.S01E01.1080p.WEB-DL.mkv"
    assert files[0].size == 2147483648
    assert files[0].progress == 1.0
    assert files[0].priority == 1


async def test_a_single_file_torrent_carries_a_bare_filename() -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_files_single"))

    files = await client.torrent_files(A_SINGLE_FILE_HASH)

    assert [file.name for file in files] == ["Some.Movie.2019.1080p.BluRay.mkv"]


async def test_a_file_name_that_walks_out_of_the_save_path_is_an_unusable_answer() -> None:
    """A torrent's file names are untrusted input, and `save_path / name` would otherwise escape."""
    client, _ = qbittorrent_client_for(
        httpx.Response(200, json=[{"index": 0, "name": "../../etc/passwd", "size": 1, "progress": 1, "priority": 1}])
    )

    with pytest.raises(ProviderUnavailableError):
        await client.torrent_files(A_MULTI_FILE_HASH)


# --- the body ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("call", ["completed_torrents", "torrent_files"])
async def test_an_oversized_body_is_refused_not_truncated(call: str) -> None:
    client, _ = qbittorrent_client_for(httpx.Response(200, content=_oversized_body()))

    with pytest.raises(ProviderResponseTooLargeError):
        await _invoke(client, call)


async def test_an_oversized_version_body_is_refused_rather_than_buffered() -> None:
    """`webapiVersion` answers plain text, so it is `read_text` that has to be capped - and it is."""
    client, _ = qbittorrent_client_for(httpx.Response(200, content=_oversized_body()), version=False)

    with pytest.raises(ProviderResponseTooLargeError):
        await client.webapi_version()


async def test_an_oversized_login_body_is_refused_rather_than_buffered() -> None:
    """The login body is the other plain-text read, and it happens before anything else this client does."""
    client, _ = qbittorrent_client_for(httpx.Response(200, content=_oversized_body()), login=False, version=False)

    with pytest.raises(ProviderResponseTooLargeError):
        await client.webapi_version()


async def test_a_body_that_is_not_json_is_an_unusable_answer() -> None:
    client, _ = qbittorrent_client_for(httpx.Response(200, content=b"<html>login</html>"))

    with pytest.raises(ProviderUnavailableError):
        await client.completed_torrents()


async def test_a_body_that_is_not_a_list_of_rows_is_an_unusable_answer() -> None:
    """qBittorrent answers arrays, not envelopes. A dict here is a server that is not qBittorrent."""
    client, _ = qbittorrent_client_for(httpx.Response(200, json={"torrents": []}))

    with pytest.raises(ProviderUnavailableError):
        await client.completed_torrents()


async def test_a_row_whose_shape_the_client_cannot_read_is_refused() -> None:
    client, _ = qbittorrent_client_for(httpx.Response(200, json=[{"name": "no hash here"}]))

    with pytest.raises(ProviderUnavailableError) as raised:
        await client.completed_torrents()

    assert "no hash here" not in str(raised.value)


# --- refusals and outages ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, ProviderNotFoundError),
        (429, ProviderRefusedError),
        (409, ProviderRefusedError),
        (500, ProviderUnavailableError),
    ],
)
@pytest.mark.parametrize("call", EVERY_CALL)
async def test_a_refusal_is_reported_as_the_status_it_is(status: int, expected: type[ProviderError], call: str) -> None:
    client, _ = qbittorrent_client_for(httpx.Response(status, text="no"), version=False)

    with pytest.raises(expected):
        await _invoke(client, call)


async def test_a_redirect_is_reported_rather_than_followed() -> None:
    """A hop would have to be re-checked against the base, and no documented endpoint issues one."""
    client, responder = qbittorrent_client_for(
        httpx.Response(302, headers={"location": "http://example.com/api/v2/torrents/info"})
    )

    with pytest.raises(ProviderUnavailableError):
        await client.completed_torrents()

    assert all("example.com" not in url for url in responder.requested)


async def test_an_unreachable_host_is_one_attempt_and_no_retry() -> None:
    client, attempts = _unreachable_client("connection refused")

    with pytest.raises(ProviderUnavailableError):
        await client.completed_torrents()

    assert len(attempts) == 1


async def test_an_unreachable_hosts_failure_is_logged_as_the_post_the_login_actually_was(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = _unreachable_client("connection refused")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError):
        await client.completed_torrents()

    line = next(message for message in _messages(caplog) if message.startswith("provider_call"))
    assert "method=POST" in line
    assert "outcome=failed" in line


# --- the credential reaches no log, no URL and no message ----------------------------------------------------


@pytest.mark.parametrize("call", EVERY_CALL)
async def test_the_credential_never_appears_in_a_log_record(caplog: pytest.LogCaptureFixture, call: str) -> None:
    """Every public call on its success path, which is every code path a credential could be written from."""
    body = "torrents_files_multi" if call == "torrent_files" else "torrents_info_completed"
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, body))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await _invoke(client, call)

    messages = _messages(caplog)
    assert messages, "the calls should have logged lines"
    assert all(A_RECORDED_QBITTORRENT_PASSWORD not in message for message in messages)
    assert all(A_RECORDED_SID not in message for message in messages)
    assert all("Cookie" not in message and "password" not in message for message in messages)


async def test_the_call_log_carries_the_fields_an_operator_reads_and_nothing_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.completed_torrents()

    line = next(message for message in _messages(caplog) if "path=/api/v2/torrents/info" in message)
    assert "method=GET" in line
    assert "host=127.0.0.1" in line
    assert "status=200" in line
    assert "outcome=fresh" in line


async def test_the_login_is_logged_as_the_post_it_actually_is(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.completed_torrents()

    line = next(message for message in _messages(caplog) if "path=/api/v2/auth/login" in message)
    assert "method=POST" in line


@pytest.mark.parametrize("call", EVERY_CALL)
async def test_no_call_puts_the_credential_in_a_log_record_or_an_exception(
    caplog: pytest.LogCaptureFixture, call: str
) -> None:
    """One sweep over every public method, so a method added later cannot quietly skip this check."""
    client, _ = qbittorrent_client_for(httpx.Response(500, text="boom"), version=False)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        try:
            await _invoke(client, call)
        except ProviderError as error:
            assert A_RECORDED_QBITTORRENT_PASSWORD not in str(error)

    assert all(A_RECORDED_QBITTORRENT_PASSWORD not in message for message in _messages(caplog))


@pytest.mark.parametrize("call", EVERY_CALL)
async def test_an_upstream_errors_text_is_never_repeated_into_the_raised_message(
    caplog: pytest.LogCaptureFixture, call: str
) -> None:
    """`unreachable()` names the error's CLASS and deliberately never its text. h11 builds its message by
    quoting the whole offending header back, so interpolating `{error}` anywhere here would carry whatever
    was in that header into the raised message, the log and whatever a service made of it."""
    client, _ = _unreachable_client(f"refused while sending {A_RECORDED_QBITTORRENT_PASSWORD}")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError) as raised:
        await _invoke(client, call)

    assert A_RECORDED_QBITTORRENT_PASSWORD not in str(raised.value)
    assert all(A_RECORDED_QBITTORRENT_PASSWORD not in message for message in _messages(caplog))
    # The chain is kept, so a traceback still names what went wrong - and asserting the CAUSE does carry
    # the text is what proves this reproduces the real leak rather than a silent transport.
    assert isinstance(raised.value.__cause__, httpx.HTTPError)
    assert A_RECORDED_QBITTORRENT_PASSWORD in str(raised.value.__cause__)


async def test_a_sid_carrying_a_newline_never_reaches_the_raised_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """qBittorrent authenticates by cookie, so the secret that h11 would quote back rides in `Cookie`.

    The login itself carries no cookie and is answered normally; the NEXT call is the one that fails on the
    header built from what the login stored.
    """
    responder = H11RejectingResponder(
        qbittorrent_login_response(sid=A_CREDENTIAL_WITH_A_NEWLINE.replace("\n", "")),
        header="Cookie",
    )
    client, _ = qbittorrent_client_for(responder=responder)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), pytest.raises(ProviderUnavailableError) as raised:
        await client.completed_torrents()

    assert "cret-newline-credential" not in str(raised.value)
    assert all("cret-newline-credential" not in message for message in _messages(caplog))
    assert isinstance(raised.value.__cause__, httpx.HTTPError)
    assert "cret-newline-credential" in str(raised.value.__cause__)


# --- the configured host is the whole allowlist ---------------------------------------------------------------


@pytest.mark.parametrize(
    "base_url", ["http://127.0.0.1:8080", "http://localhost:8080", "http://192.168.1.20:8080", "https://qb.lan:8443"]
)
async def test_a_private_or_loopback_base_is_accepted_because_that_is_where_qbittorrent_lives(base_url: str) -> None:
    """`agent/url_guard.assert_public_http_url` rejects loopback by design, and `assert_within_base` requires
    https - which is why this client is pinned by `assert_within_configured_base` instead."""
    responder = RecordingResponder(qbittorrent_login_response(), fixture_text_response(QBITTORRENT, "webapi_version"))
    client, _ = qbittorrent_client_for(base_url=base_url, responder=responder)

    assert await client.webapi_version() == "2.11.4"


@pytest.mark.parametrize("base_url", ["ftp://127.0.0.1:8080", "file:///etc", "ws://127.0.0.1:8080"])
def test_a_base_url_that_is_not_http_is_refused_where_the_pool_is_pinned_to_it(base_url: str) -> None:
    with pytest.raises(OutboundUrlError):
        build_qbittorrent_http(base_url)


def test_a_base_url_carrying_credentials_is_refused_the_same_way() -> None:
    with pytest.raises(OutboundUrlError):
        build_qbittorrent_http("http://user:pass@127.0.0.1:8080")


async def test_the_pool_an_unconfigured_client_holds_can_still_reach_nothing() -> None:
    """Belt and braces: `configured` refuses first, and the pool it holds is pinned to a dead loopback port."""
    answered: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        answered.append(request)
        return httpx.Response(200)

    async with build_qbittorrent_http(UNCONFIGURED_UPSTREAM_BASE_URL, transport=httpx.MockTransport(answer)) as http:
        with pytest.raises(OutboundUrlError):
            await http.get("http://evil/api/v2/torrents/info")

    assert answered == []


# --- the composition seam --------------------------------------------------------------------------------------


def test_build_qbittorrent_client_reads_all_three_values_off_settings() -> None:
    settings = Settings(
        _env_file=None,
        qbittorrent_url=A_QBITTORRENT_BASE_URL,
        qbittorrent_user=A_RECORDED_QBITTORRENT_USER,
        qbittorrent_password=SecretStr(A_RECORDED_QBITTORRENT_PASSWORD),
    )

    assert build_qbittorrent_client(settings).configured is True


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"qbittorrent_url": A_QBITTORRENT_BASE_URL},
        {"qbittorrent_url": A_QBITTORRENT_BASE_URL, "qbittorrent_user": A_RECORDED_QBITTORRENT_USER},
    ],
)
def test_build_qbittorrent_client_is_disabled_rather_than_broken_with_anything_missing(
    overrides: dict[str, str],
) -> None:
    assert build_qbittorrent_client(Settings(_env_file=None, **overrides)).configured is False


async def test_a_client_closes_the_pool_it_holds() -> None:
    client, _ = qbittorrent_client_for(fixture_response(QBITTORRENT, "torrents_info_completed"))

    assert client.closed is False
    await client.aclose()

    assert client.closed is True
    with pytest.raises(RuntimeError):
        await client.completed_torrents()


# --- the fixtures are what the wiki documents -------------------------------------------------------------------


def test_the_recorded_bodies_carry_the_forty_hex_hashes_the_client_pins_to() -> None:
    """A fixture that drifted from the documented shape would make every test above pass against nothing."""
    rows = fixture_rows(QBITTORRENT, "torrents_info_completed")

    assert len(rows) == 4
    assert all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(row["hash"])) for row in rows)
    assert sorted(len(str(row["hash"])) for row in rows) == [40, 40, 40, 64]
