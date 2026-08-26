import type { WatchCounts } from "./WatchCounts";

export interface CategorySummary {
  id: string;
  name: string;
  file_name: string;
  sheet_title: string;
  accent: string;
  mtime: number;
  has_watch_column: boolean;
  locked_by_excel: boolean;
  hero_url?: string | null;
  counts: WatchCounts;
}
