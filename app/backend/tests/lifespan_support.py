"""Drive an ASGI app through startup and shutdown the way the server does."""

from __future__ import annotations

from fastapi import FastAPI


async def run_lifespan(app: FastAPI) -> None:
    """Take an app through startup and shutdown the way the ASGI server does."""
    events: list[dict[str, str]] = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

    async def receive() -> dict[str, str]:
        return events.pop(0)

    async def send(message: dict[str, str]) -> None:
        return None

    await app({"type": "lifespan"}, receive, send)
