"""FastAPI application exposing the Excel watch-order library."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tv_watchlist.agent.dependencies import get_agent_runtime
from tv_watchlist.api import categories, chat, entries, errors, library, playback, review, rows, watch_events
from tv_watchlist.api.dependencies import get_ingest_runtime, get_jellyfin_client, get_qbittorrent_client
from tv_watchlist.config import get_settings
from tv_watchlist.data.session import get_engine


@asynccontextmanager
async def _shut_agent_down_with_the_app(_: FastAPI) -> AsyncIterator[None]:
    """Chromium, the CLI subprocesses a chat starts, the provider pools and the database pool must not
    outlive the backend. The engine goes last, because the ingest runtime holds sessions built on it."""
    yield
    await get_agent_runtime().aclose()
    # Only if something actually ingested. Unlike the agent runtime, which holds nothing until a chat
    # escalates, constructing this one opens two provider connection pools - so asking for it here would
    # build the very thing it is being asked to close. The agent line stays unguarded deliberately: two
    # existing tests substitute a plain callable for `get_agent_runtime`, which has no `cache_info`.
    if get_ingest_runtime.cache_info().currsize:
        await get_ingest_runtime().aclose()
    # Guarded for the same reason, and for one more: building this one reads `jellyfin_base_url`, so an
    # unguarded call here would pin a pool to the media server during shutdown of an app that never
    # touched it.
    if get_jellyfin_client.cache_info().currsize:
        await get_jellyfin_client().aclose()
    # And the same again for the WebUI pool, which is guarded for the same two reasons.
    if get_qbittorrent_client.cache_info().currsize:
        await get_qbittorrent_client().aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    """Build the application with CORS scoped to the local frontend."""
    settings = get_settings()
    app = FastAPI(title="TV Watch List", version="0.1.0", lifespan=_shut_agent_down_with_the_app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{settings.frontend_port}",
            f"http://127.0.0.1:{settings.frontend_port}",
        ],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    errors.register(app)
    app.include_router(categories.router)
    app.include_router(entries.router)
    app.include_router(library.router)
    app.include_router(playback.router)
    app.include_router(review.router)
    app.include_router(rows.router)
    app.include_router(watch_events.router)
    app.include_router(chat.router)

    # Drop an image named after a category id in here and its card uses it.
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/heroes", StaticFiles(directory=settings.heroes_dir), name="heroes")
    return app


app = create_app()
