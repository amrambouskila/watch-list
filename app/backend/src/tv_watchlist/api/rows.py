"""Row-level endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.row_write import RowWrite
from tv_watchlist.services.catalog import Catalog

router = APIRouter(prefix="/api/categories/{category_id}/rows", tags=["rows"])

CatalogDep = Annotated[Catalog, Depends(get_catalog)]


@router.post("", response_model=CategoryDetail)
async def append_row(category_id: str, payload: RowWrite, catalog: CatalogDep) -> CategoryDetail:
    """Add a row to the end of the sheet."""
    return await catalog.append_row(category_id, payload)


@router.patch("/{row}", response_model=CategoryDetail)
async def update_row(category_id: str, row: int, payload: RowWrite, catalog: CatalogDep) -> CategoryDetail:
    """Write one row's cells."""
    return await catalog.update_row(category_id, row, payload)


@router.delete("/{row}", response_model=CategoryDetail)
async def delete_row(
    category_id: str,
    row: int,
    catalog: CatalogDep,
    expected_mtime: Annotated[float, Query()],
) -> CategoryDetail:
    """Remove one row from the sheet."""
    return await catalog.delete_row(category_id, row, expected_mtime)
