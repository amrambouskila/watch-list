import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function addWatchColumn(categoryId: string, expectedMtime: number): Promise<CategoryDetail> {
  const query = new URLSearchParams({ expected_mtime: String(expectedMtime) });
  return request<CategoryDetail>(
    `/api/categories/${encodeURIComponent(categoryId)}/watch-column?${query}`,
    { method: "POST" },
  );
}
