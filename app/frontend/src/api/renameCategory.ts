import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function renameCategory(categoryId: string, stem: string, expectedMtime: number): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/categories/${encodeURIComponent(categoryId)}/rename`, {
    method: "POST",
    body: JSON.stringify({ stem, expected_mtime: expectedMtime }),
  });
}
