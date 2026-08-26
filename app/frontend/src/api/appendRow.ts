import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function appendRow(
  categoryId: string,
  cells: Record<string, string>,
  expectedMtime: number,
): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/categories/${encodeURIComponent(categoryId)}/rows`, {
    method: "POST",
    body: JSON.stringify({ cells, expected_mtime: expectedMtime }),
  });
}
