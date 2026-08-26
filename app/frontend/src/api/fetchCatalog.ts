import type { CatalogListing } from "../types/CatalogListing";
import { request } from "./request";

export function fetchCatalog(): Promise<CatalogListing> {
  return request<CatalogListing>("/api/categories");
}
