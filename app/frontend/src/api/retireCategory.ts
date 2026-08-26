import type { CatalogListing } from "../types/CatalogListing";
import { request } from "./request";

/** Retiring answers with the library that is left, since the category it took away has no detail. */
export function retireCategory(categoryId: string, expectedMtime: number): Promise<CatalogListing> {
  const query = new URLSearchParams({ expected_mtime: String(expectedMtime) });
  return request<CatalogListing>(`/api/categories/${encodeURIComponent(categoryId)}?${query}`, {
    method: "DELETE",
  });
}
