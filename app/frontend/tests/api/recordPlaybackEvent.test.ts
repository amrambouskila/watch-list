import { expect, it } from "vitest";

import { recordPlaybackEvent } from "../../src/api/recordPlaybackEvent";
import { aFakeServer } from "../support/aFakeServer";

it("records the captured subject with paired player context and no browser credentials", async () => {
  const server = aFakeServer();
  server.answers("POST /api/watch-events", { id: "event" });
  const body = { subject_kind: "episode" as const, subject_id: "episode", kind: "progressed" as const,
    occurred_at: "2026-09-24T10:00:00Z", position_seconds: 60, runtime_seconds: 120 };
  const event = await recordPlaybackEvent("entry/one", "file/one", body);
  expect(event.id).toBe("event");
  expect(server.requests[0]?.body).toEqual(body);
  expect(new URLSearchParams(server.requests[0]?.query).get("playback_entry_id")).toBe("entry/one");
  expect(new URLSearchParams(server.requests[0]?.query).get("jellyfin_item_id")).toBe("file/one");
});
