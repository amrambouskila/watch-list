import { describe, expect, it } from "vitest";

import { IN_PROGRESS, SKIPPED, UNWATCHED, WATCHED } from "../../src/types/WatchStatus";
import { statusLabel } from "../../src/utils/statusLabel";

describe("statusLabel", () => {
  it.each([
    [UNWATCHED, "Not started"],
    [WATCHED, "Watched"],
    [IN_PROGRESS, "Watching"],
    [SKIPPED, "Skipped"],
  ])("reads %j as %s", (status, label) => {
    expect(statusLabel(status)).toBe(label);
  });

  it("shows a value the sheet invented as the sheet wrote it, rather than hiding it", () => {
    expect(statusLabel("Rewatching")).toBe("Rewatching");
  });
});
