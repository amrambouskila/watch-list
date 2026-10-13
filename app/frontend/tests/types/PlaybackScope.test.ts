import { expectTypeOf, it } from "vitest";

import type { PlaybackScope } from "../../src/types/PlaybackScope";

it("captures immutable workbook context independently of active navigation", () => {
  expectTypeOf<PlaybackScope>().toEqualTypeOf<{
    readonly entryId: string; readonly title: string; readonly categoryId: string; readonly mtime: number;
  }>();
});
