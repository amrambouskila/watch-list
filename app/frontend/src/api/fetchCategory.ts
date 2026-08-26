import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export function fetchCategory(categoryId: string): Promise<CategoryDetail> {
  return request<CategoryDetail>(`/api/categories/${encodeURIComponent(categoryId)}`);
}
