"""Category-level endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from tv_watchlist.api.dependencies import get_catalog
from tv_watchlist.models.catalog_listing import CatalogListing
from tv_watchlist.models.category_create import CategoryCreate
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.category_rename import CategoryRename
from tv_watchlist.services.catalog import Catalog

router = APIRouter(prefix="/api/categories", tags=["categories"])

CatalogDep = Annotated[Catalog, Depends(get_catalog)]


@router.get("", response_model=CatalogListing)
async def list_categories(catalog: CatalogDep) -> CatalogListing:
    """Every workbook in the library, rescanned on each call."""
    return await catalog.listing()


@router.post("", response_model=CategoryDetail, status_code=status.HTTP_201_CREATED)
async def create_category(payload: CategoryCreate, catalog: CatalogDep) -> CategoryDetail:
    """Generate a new category workbook in the library folder."""
    return await catalog.create_category(payload)


@router.get("/{category_id}", response_model=CategoryDetail)
async def get_category(category_id: str, catalog: CatalogDep) -> CategoryDetail:
    """One category with its full grid."""
    return await catalog.detail(category_id)


@router.delete("/{category_id}", response_model=CatalogListing)
async def retire_category(
    category_id: str,
    catalog: CatalogDep,
    expected_mtime: Annotated[float, Query()],
) -> CatalogListing:
    """Move a category's workbook and artwork into the backups folder; the library stops listing it."""
    return await catalog.retire_category(category_id, expected_mtime)


@router.post("/{category_id}/rename", response_model=CategoryDetail)
async def rename_category(category_id: str, payload: CategoryRename, catalog: CatalogDep) -> CategoryDetail:
    """Rename the workbook behind a category; its id changes with its filename."""
    return await catalog.rename_category(category_id, payload)


@router.post("/{category_id}/watch-column", response_model=CategoryDetail)
async def add_watch_column(
    category_id: str,
    catalog: CatalogDep,
    expected_mtime: Annotated[float, Query()],
) -> CategoryDetail:
    """Add the standard Watched? column to a sheet that does not have one."""
    return await catalog.add_watch_column(category_id, expected_mtime)
