import type { CategorySummary } from "./CategorySummary";

export interface UnreadableWorkbook {
  file_name: string;
  reason: string;
}

/** A file the app cannot reach: another file already answers to the id this one's name derives. */
export interface ShadowedWorkbook {
  file_name: string;
  category_id: string;
  answered_by: string;
}

export interface CatalogListing {
  categories: CategorySummary[];
  unreadable: UnreadableWorkbook[];
  shadowed: ShadowedWorkbook[];
  library_dir: string;
}
