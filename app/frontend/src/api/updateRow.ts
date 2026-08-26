import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function updateRow(
  categoryId: string,
  row: number,
  cells: Record<string, string>,
  expectedMtime: number,
): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/categories/${encodeURIComponent(categoryId)}/rows/${row}`, {
    method: "PATCH",
    body: JSON.stringify({ cells, expected_mtime: expectedMtime }),
  });
}
