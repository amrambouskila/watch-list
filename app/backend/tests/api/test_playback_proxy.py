from __future__ import annotations

import asyncio
import gzip
import logging
import traceback
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from episode_join_support import file_id
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message

from playback_server import PlaybackServer
from playback_stream import PlaybackStream
from provider_fixtures import A_JELLYFIN_BASE_URL, A_RECORDED_JELLYFIN_KEY
from tv_watchlist.api.dependencies import get_jellyfin_client
from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import JellyfinItemKind
from tv_watchlist.data.models import JellyfinItem
from tv_watchlist.data.session import get_session
from tv_watchlist.main import create_app


async def _file(session: AsyncSession, kind: JellyfinItemKind = JellyfinItemKind.MOVIE) -> JellyfinItem:
    row = JellyfinItem(jellyfin_id=file_id(1), name="A file", kind=kind)
    session.add(row)
    await session.flush()
    return row


@pytest.mark.parametrize("ranged", [False, True])
async def test_stream_relays_bytes_status_and_only_the_allowed_headers(
    db_session: AsyncSession, ranged: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    row = await _file(db_session)
    server = PlaybackServer(
        status=206 if ranged else 200,
        body=b"ab",
        headers={
            "Content-Type": "video/webm",
            "Content-Length": "2",
            "Content-Range": "bytes 0-1/5",
            "Set-Cookie": "private=secret",
            "Server": "Jellyfin",
            "X-Jellyfin-Version": "private",
        },
    )
    headers = {"Cookie": "owner=secret", "Authorization": "caller-secret", "X-Forwarded-For": "spoofed"}
    if ranged:
        headers["Range"] = "bytes=0-1"
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream", headers=headers)
    assert response.status_code == (206 if ranged else 200)
    assert response.content == b"ab"
    assert set(response.headers) == {"content-type", "content-length", "content-range", "accept-ranges"}
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/webm"
    request = server.requests[-1]
    assert request.headers.get("range") == ("bytes=0-1" if ranged else None)
    assert "cookie" not in request.headers and "x-forwarded-for" not in request.headers
    assert request.headers["authorization"] != "caller-secret"
    assert request.url.path == f"/Videos/{row.jellyfin_id}/stream"
    assert dict(request.url.params) == {"static": "true"}
    for secret in (A_JELLYFIN_BASE_URL, A_RECORDED_JELLYFIN_KEY, row.jellyfin_id):
        assert secret not in response.text and secret not in str(response.headers)
    assert A_RECORDED_JELLYFIN_KEY not in caplog.text


@pytest.mark.parametrize(
    "header",
    [
        "bytes=abc",
        "bytes=0-1,5-6",
        "items=0-1",
        "bytes=0-1\r\nX-Injected: 1",
        "bytes=-1",
        "bytes=-",
        "bytes=3-2",
        "bytes=0-1\n",
        "bytes= 1-2",
        "bytes=1 -2",
        "bytes=+1-2",
    ],
)
async def test_invalid_ranges_are_refused_before_any_upstream_call(db_session: AsyncSession, header: str) -> None:
    row = await _file(db_session)
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream", headers={"Range": header})
    assert response.status_code == 416
    assert response.json()["error"] == "PlaybackRangeError"
    assert A_RECORDED_JELLYFIN_KEY not in response.text + str(response.headers)
    assert server.requests == []


@pytest.mark.parametrize("shape", ["unknown", "removed", "series"])
async def test_only_live_movie_or_episode_files_are_streamable(db_session: AsyncSession, shape: str) -> None:
    row = await _file(db_session, JellyfinItemKind.SERIES if shape == "series" else JellyfinItemKind.MOVIE)
    if shape == "removed":
        row.removed_at = utcnow()
        await db_session.flush()
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{uuid.uuid4() if shape == 'unknown' else row.id}/stream")
    assert response.status_code == 404
    assert A_RECORDED_JELLYFIN_KEY not in response.text + str(response.headers)
    assert server.requests == []


@pytest.mark.parametrize("shape", ["disabled", "unreachable", "connection", "refused", "redirect", "empty"])
async def test_failures_are_typed_and_never_echo_upstream_secrets(
    db_session: AsyncSession, shape: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    row = await _file(db_session)
    server = PlaybackServer(
        configured=shape != "disabled",
        healthy=shape != "unreachable",
        failure=shape == "connection",
        status={"refused": 401, "redirect": 302, "empty": 204}.get(shape, 200),
        body=A_RECORDED_JELLYFIN_KEY.encode(),
    )
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream")
    assert response.status_code == (503 if shape in {"disabled", "unreachable"} else 502)
    assert response.json()["error"] == (
        "JellyfinUnavailableError" if response.status_code == 503 else "PlaybackUpstreamError"
    )
    assert response.json()["message"] != response.json()["detail"]
    assert A_RECORDED_JELLYFIN_KEY not in response.text + str(response.headers) + caplog.text
    assert A_JELLYFIN_BASE_URL not in response.text


async def test_missing_content_type_defaults_to_video_mp4(db_session: AsyncSession) -> None:
    row = await _file(db_session, JellyfinItemKind.EPISODE)
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize("length", [None, "0"])
async def test_empty_successful_body_keeps_only_the_upstream_content_length(
    db_session: AsyncSession, length: str | None
) -> None:
    row = await _file(db_session)
    server = PlaybackServer(body=b"", headers={"Content-Length": length} if length is not None else {})
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream")
    assert response.status_code == 200
    assert response.headers.get("content-length") == length
    assert response.content == b""


async def test_compressed_media_is_refused_before_decoding_invalidates_length(db_session: AsyncSession) -> None:
    row = await _file(db_session)
    compressed = gzip.compress(b"media bytes")
    server = PlaybackServer(
        body=compressed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(compressed))}
    )
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream")
    assert response.status_code == 502
    assert response.json()["error"] == "PlaybackUpstreamError"
    assert server.requests[-1].headers["accept-encoding"] == "identity"
    assert server.requests[0].headers["accept-encoding"] != "identity"


@pytest.mark.parametrize("value", ["bytes=0-", "bytes=001-002", "bytes=0-0", "bytes=" + "9" * 5000 + "-"])
async def test_valid_ascii_ranges_are_forwarded_verbatim_without_integer_overflow(
    db_session: AsyncSession, value: str
) -> None:
    row = await _file(db_session)
    server = PlaybackServer(status=206)
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream", headers={"Range": value})
    assert response.status_code == 206
    assert server.requests[-1].headers["range"] == value


@pytest.mark.parametrize(
    "headers", [[(b"range", b"bytes=0-1"), (b"range", b"bytes=2-3")], [(b"range", b"bytes=\xb2-3")]]
)
async def test_duplicate_or_non_ascii_ranges_are_refused_without_echo(
    db_session: AsyncSession, headers: list[tuple[bytes, bytes]]
) -> None:
    row = await _file(db_session)
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream", headers=headers)
    assert response.status_code == 416
    assert not server.requests


@pytest.mark.parametrize("identifier", ["https://foreign.example/private", "abc", ".."])
async def test_a_url_or_untyped_provider_id_cannot_address_the_stream(
    db_session: AsyncSession, identifier: str
) -> None:
    server = PlaybackServer()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{identifier}/stream")
    assert response.status_code in {404, 422}
    assert not server.requests


async def test_real_route_mid_body_failure_has_no_error_bytes_or_secret_traceback(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    row = await _file(db_session)
    upstream = PlaybackStream(fail_at=1)
    server = PlaybackServer(stream=upstream)
    async with server.wired(db_session) as client:
        with pytest.raises(RuntimeError, match="response already started") as caught:
            await client.get(f"/api/playback/{row.id}/stream")
    assert upstream.closed and upstream.produced == 1
    assert A_RECORDED_JELLYFIN_KEY not in "".join(traceback.format_exception(caught.value)) + caplog.text


async def test_stream_releases_the_read_transaction_before_sending_headers_or_body(db_session: AsyncSession) -> None:
    row = await _file(db_session)
    path = f"/api/playback/{row.id}/stream"
    upstream = PlaybackStream()
    server = PlaybackServer(stream=upstream)
    app = create_app()
    ended = False

    async def request_session() -> AsyncIterator[AsyncSession]:
        nonlocal ended
        try:
            yield db_session
        finally:
            await db_session.close()
            ended = True

    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_jellyfin_client] = lambda: server.client
    messages: list[Message] = []

    async def send(message: Message) -> None:
        assert ended and not db_session.in_transaction()
        messages.append(message)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("no read from downstream is needed")

    try:
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "server": ("test", 80),
                "client": ("test", 123),
            },
            receive,
            send,
        )
    finally:
        await server.client.aclose()
    assert messages[0]["status"] == 200
    assert upstream.closed and upstream.produced == 3


async def test_a_closed_jellyfin_pool_is_a_safe_503_before_health(db_session: AsyncSession) -> None:
    row = await _file(db_session)
    server = PlaybackServer()
    await server.client.aclose()
    async with server.wired(db_session) as client:
        response = await client.get(f"/api/playback/{row.id}/stream")
    assert response.status_code == 503
    assert not server.requests


async def test_failed_database_teardown_never_opens_a_media_stream(db_session: AsyncSession) -> None:
    row = await _file(db_session)
    server = PlaybackServer(stream=PlaybackStream())
    app = create_app()

    async def request_session() -> AsyncIterator[AsyncSession]:
        yield db_session
        raise RuntimeError("database cleanup failed")

    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_jellyfin_client] = lambda: server.client
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            with pytest.raises(RuntimeError, match="database cleanup failed"):
                await client.get(f"/api/playback/{row.id}/stream")
    finally:
        await server.client.aclose()
    assert [request.url.path for request in server.requests] == ["/health"]
