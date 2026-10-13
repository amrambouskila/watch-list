import { expectTypeOf, it } from "vitest";

import type { PlaybackScope } from "../../src/types/PlaybackScope";
import type { PlaybackSnapshot } from "../../src/types/PlaybackSnapshot";
import type { WatchEventCreate } from "../../src/types/WatchEventCreate";

it("keeps the selected file and captured event together through retries", () => {
  expectTypeOf<PlaybackSnapshot>().toEqualTypeOf<{
    readonly id: string; readonly scope: PlaybackScope; readonly fileId: string; readonly event: WatchEventCreate;
  }>();
});
