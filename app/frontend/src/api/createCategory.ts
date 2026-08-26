import type { CategoryDetail } from "../types/CategoryDetail";
import { request } from "./request";

export interface CategoryDraft {
  readonly name: string;
  readonly accent: string;
  readonly titles: readonly string[];
}

export function createCategory(draft: CategoryDraft): Promise<CategoryDetail> {
  return request<CategoryDetail>("/api/categories", {
    method: "POST",
    body: JSON.stringify({ name: draft.name, accent: draft.accent, titles: draft.titles }),
  });
}
