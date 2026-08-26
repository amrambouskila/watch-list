import type { CatalogListing } from "../types/CatalogListing";
import type { CategorySummary } from "../types/CategorySummary";

/** The library's entry for one category, or null while the library has not been read. */
export function categoryIn(listing: CatalogListing | null, categoryId: string): CategorySummary | null {
  return listing?.categories.find((category) => category.id === categoryId) ?? null;
}
