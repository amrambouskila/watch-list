import { expectTypeOf, it } from "vitest";

import type { PositionWrite } from "../../src/types/PositionWrite";

it("mirrors exactly the server projection request", () => {
  expectTypeOf<keyof PositionWrite>().toEqualTypeOf<"watch_event_id" | "expected_mtime">();
  expectTypeOf<PositionWrite>().toEqualTypeOf<{ watch_event_id: string; expected_mtime: number }>();
});
