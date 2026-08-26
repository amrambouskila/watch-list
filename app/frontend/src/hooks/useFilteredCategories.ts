import { useMemo } from "react";

import type { CategorySummary } from "../types/CategorySummary";
import { useAppSelector } from "./useAppSelector";

/**
 * The category list narrowed by the shared search term.
 *
 * The sidebar and the home cards show the same library, so they read one query rather than
 * keeping separate boxes that could disagree about what is being filtered.
 *
 * Only the display name is matched. Matching the filename too sounds useful but is not: every
 * workbook here is named `..._Master_Watch_Order`, so "ma" would return the whole library.
 */
export function useFilteredCategories(): readonly CategorySummary[] {
  const listing = useAppSelector((state) => state.catalog.listing);
  const query = useAppSelector((state) => state.ui.categoryQuery);

  return useMemo(() => {
    const all = listing?.categories ?? [];
    const needle = query.trim().toLowerCase();
    if (needle === "") return all;
    return all.filter((category) => category.name.toLowerCase().includes(needle));
  }, [listing, query]);
}
