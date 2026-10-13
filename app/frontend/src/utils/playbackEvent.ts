import type { PlaybackItemRead } from "../types/PlaybackItemRead";
import type { WatchEventCreate } from "../types/WatchEventCreate";

/** Convert native media seconds once into an integer-second watch event. */
export function playbackEvent(
  item: PlaybackItemRead,
  kind: "progressed" | "completed",
  position: number,
  runtime: number,
  occurredAt: string,
): WatchEventCreate | null {
  const subjectId = item.episode_id ?? item.movie_title_id;
  if (subjectId === null || !Number.isFinite(position) || position < 0) return null;
  const positionSeconds = Math.round(position);
  const roundedRuntime = Number.isFinite(runtime) ? Math.round(runtime) : 0;
  const runtimeSeconds = roundedRuntime > 0 ? roundedRuntime : null;
  if (kind === "completed" && (runtimeSeconds === null || positionSeconds < runtimeSeconds)) return null;
  return {
    subject_kind: item.episode_id !== null ? "episode" : "title",
    subject_id: subjectId,
    kind,
    occurred_at: occurredAt,
    position_seconds: runtimeSeconds === null ? positionSeconds : Math.min(positionSeconds, runtimeSeconds),
    runtime_seconds: runtimeSeconds,
  };
}
