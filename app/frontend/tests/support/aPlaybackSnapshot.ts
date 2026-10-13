import type { PlaybackSnapshot } from "../../src/types/PlaybackSnapshot";

let sequence = 0;

export function aPlaybackSnapshot(overrides: Partial<PlaybackSnapshot> = {}): PlaybackSnapshot {
  sequence += 1;
  return {
    id: `snapshot-${sequence}`,
    scope: { entryId: "entry", title: "A Show", categoryId: `playback-${sequence}`, mtime: 1 },
    fileId: "file",
    event: { subject_kind: "episode", subject_id: "episode", kind: "progressed",
      position_seconds: 60, runtime_seconds: 120, occurred_at: "2026-09-24T10:00:00Z" },
    ...overrides,
  };
}
