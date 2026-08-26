"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from tv_watchlist.config import get_settings
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.hero_store import HeroStore


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Process-wide catalog, so the workbook cache is shared across requests."""
    return Catalog(get_settings())


@lru_cache(maxsize=1)
def get_hero_store() -> HeroStore:
    """Process-wide hero store, writing through the same catalog the endpoints read from."""
    return HeroStore(get_catalog(), get_settings())
