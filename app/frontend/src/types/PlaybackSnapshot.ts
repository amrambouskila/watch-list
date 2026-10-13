import type { PlaybackScope } from "./PlaybackScope";
import type { WatchEventCreate } from "./WatchEventCreate";

export interface PlaybackSnapshot {
  readonly id: string;
  readonly scope: PlaybackScope;
  readonly fileId: string;
  readonly event: WatchEventCreate;
}
