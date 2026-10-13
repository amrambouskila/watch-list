import type { RootState } from "./store";

export function hasPendingWrites(state: RootState): boolean {
  return Object.keys(state.category.pending).length > 0 ||
    Object.values(state.playbackSaves.jobs).some((job) => job.status === "saving");
}
