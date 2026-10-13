from __future__ import annotations

import asyncio
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope

from playback_server import PlaybackServer
from playback_stream import PlaybackStream
from provider_fixtures import A_RECORDED_JELLYFIN_KEY
from tv_watchlist.api.playback_response import PlaybackResponse
from tv_watchlist.clients.streamed_response import StreamedResponse
from tv_watchlist.data.errors import PlaybackUpstreamError


async def test_content_type_header_casing_cannot_add_a_second_fallback_header() -> None:
    upstream = PlaybackStream()

    @asynccontextmanager
    async def context() -> AsyncIterator[StreamedResponse]:
        yield StreamedResponse(status_code=200, headers={"content-type": "video/webm"}, body=upstream.__aiter__())

    headers: list[tuple[bytes, bytes]] = []

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers.extend(message["headers"])

    await PlaybackResponse(context())(_scope(), _waiting_receive, send)
    assert [value for key, value in headers if key == b"content-type"] == [b"video/webm"]


def _response(server: PlaybackServer) -> PlaybackResponse:
    return PlaybackResponse(server.client.stream("a" * 32, range_header=None))


async def _waiting_receive() -> Message:
    await asyncio.Event().wait()
    raise AssertionError("receive must be cancelled")


def _scope(version: str = "2.4") -> Scope:
    return {"type": "http", "asgi": {"spec_version": version}}


async def test_downstream_receives_each_chunk_before_the_next_is_produced() -> None:
    upstream = PlaybackStream(count=10_000)
    server = PlaybackServer(stream=upstream)
    response = _response(server)
    sent = 0

    async def send(message: Message) -> None:
        nonlocal sent
        if message["type"] == "http.response.body" and message["body"]:
            sent += 1
            assert upstream.produced == sent
            await anyio.sleep(0)

    try:
        await response(_scope(), _waiting_receive, send)
    finally:
        await server.client.aclose()
    assert sent == upstream.count
    assert upstream.closed


@pytest.mark.parametrize("stage", ["headers", "body"])
async def test_send_side_disconnect_closes_upstream_even_before_iteration(stage: str) -> None:
    upstream = PlaybackStream()
    server = PlaybackServer(stream=upstream)
    response = _response(server)

    async def send(message: Message) -> None:
        if message["type"] == ("http.response.start" if stage == "headers" else "http.response.body"):
            raise OSError("client gone")

    try:
        with pytest.raises(ClientDisconnect):
            await response(_scope(), _waiting_receive, send)
    finally:
        await server.client.aclose()
    assert upstream.closed
    assert upstream.produced == (0 if stage == "headers" else 1)


@pytest.mark.parametrize("stage", ["headers", "body", "read"])
async def test_asgi_disconnect_cancellation_shields_upstream_cleanup(stage: str) -> None:
    upstream = PlaybackStream(block_at=0 if stage == "read" else None)
    server = PlaybackServer(stream=upstream)
    response = _response(server)
    ready = upstream.waiting if stage == "read" else asyncio.Event()

    async def send(message: Message) -> None:
        if stage == "headers" or (stage == "body" and message["type"] == "http.response.body"):
            ready.set()
            await asyncio.Event().wait()

    async def receive() -> Message:
        await ready.wait()
        return {"type": "http.disconnect"}

    try:
        with anyio.fail_after(2):
            await response(_scope("2.0"), receive, send)
    finally:
        await server.client.aclose()
    assert upstream.closed


@pytest.mark.parametrize("fail_at", [0, 1])
async def test_mid_stream_errors_terminate_without_injecting_error_text(fail_at: int) -> None:
    upstream = PlaybackStream(fail_at=fail_at)
    server = PlaybackServer(stream=upstream)
    response = _response(server)
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    try:
        with pytest.raises(PlaybackUpstreamError) as caught:
            await response(_scope(), _waiting_receive, send)
    finally:
        await server.client.aclose()
    assert upstream.closed
    assert messages[0]["type"] == "http.response.start"
    assert len(messages) == fail_at + 1
    assert A_RECORDED_JELLYFIN_KEY not in str(messages) + "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "ReadError"


async def test_cleanup_errors_are_sanitized_even_when_the_body_never_started() -> None:
    upstream = PlaybackStream(fail_close=True)
    server = PlaybackServer(stream=upstream)
    response = _response(server)

    async def send(_: Message) -> None:
        raise OSError("client gone")

    try:
        with pytest.raises(PlaybackUpstreamError) as caught:
            await response(_scope(), _waiting_receive, send)
    finally:
        await server.client.aclose()
    assert upstream.closed
    assert A_RECORDED_JELLYFIN_KEY not in "".join(traceback.format_exception(caught.value))


async def test_disconnect_while_sending_a_502_does_not_chain_the_original_secret_error() -> None:
    server = PlaybackServer(failure=True)

    async def send(_: Message) -> None:
        raise OSError("client gone")

    try:
        with pytest.raises(OSError) as caught:
            await _response(server)(_scope(), _waiting_receive, send)
    finally:
        await server.client.aclose()
    assert A_RECORDED_JELLYFIN_KEY not in "".join(traceback.format_exception(caught.value))
