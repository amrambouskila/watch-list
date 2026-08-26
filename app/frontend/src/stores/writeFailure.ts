import { ApiError } from "../api/ApiError";
import { fetchCategory } from "../api/fetchCategory";
import type { CategoryDetail } from "../types/CategoryDetail";
import { noteMtime } from "./writeQueue";

export interface WriteFailure {
  readonly message: string;
  /** Present when the workbook changed underneath us and was reloaded instead of overwritten. */
  readonly refreshed: CategoryDetail | null;
}

export async function toWriteFailure(error: unknown, categoryId: string): Promise<WriteFailure> {
  const message = error instanceof Error ? error.message : "That change did not save.";
  const stale = error instanceof ApiError && error.isStale;
  const refreshed = stale ? await fetchCategory(categoryId).catch(() => null) : null;
  if (refreshed !== null) noteMtime(categoryId, refreshed.mtime);
  return { message, refreshed };
}
