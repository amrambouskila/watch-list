import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function deleteRow(categoryId: string, row: number, expectedMtime: number): Promise<CategoryDetail> {
  const query = new URLSearchParams({ expected_mtime: String(expectedMtime) });
  return request<CategoryDetail>(`/api/categories/${encodeURIComponent(categoryId)}/rows/${row}?${query}`, {
    method: "DELETE",
  });
}
