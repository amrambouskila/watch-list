import { expect, it } from "vitest";

import { writePlaybackPosition } from "../../src/api/writePlaybackPosition";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer } from "../support/aFakeServer";

it("projects only the committed event and guarded workbook stamp", async () => {
  const server = aFakeServer();
  const detail = aCategoryDetail();
  server.answers("POST /api/playback/entries/entry%2Fone/position", detail);
  expect(await writePlaybackPosition("entry/one", { watch_event_id: "event", expected_mtime: 42 })).toEqual(detail);
  expect(server.requests[0]?.body).toEqual({ watch_event_id: "event", expected_mtime: 42 });
});
