import { describe, expect, it } from "vitest";

import { entryCount } from "../../src/utils/entryCount";

describe("entryCount", () => {
  it.each([
    [0, "0 entries"],
    [1, "1 entry"],
    [2, "2 entries"],
    [996, "996 entries"],
  ])("says %i as %s", (count, said) => {
    expect(entryCount(count)).toBe(said);
  });
});
