"""FastAPI application exposing the Excel watch-order library."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tv_watchlist.agent.dependencies import get_agent_runtime
from tv_watchlist.api import categories, chat, errors, rows
from tv_watchlist.config import get_settings


@asynccontextmanager
async def _shut_agent_down_with_the_app(_: FastAPI) -> AsyncIterator[None]:
    """Chromium and the CLI subprocesses a chat starts must not outlive the backend."""
    yield
    await get_agent_runtime().aclose()


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
    app.include_router(rows.router)
    app.include_router(chat.router)

    # Drop an image named after a category id in here and its card uses it.
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/heroes", StaticFiles(directory=settings.heroes_dir), name="heroes")
    return app


app = create_app()
