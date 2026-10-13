import { expect, it } from "vitest";

import { loadCategory, writeRow } from "../../src/stores/categorySlice";
import { eventRecorded, savePlaybackSnapshot } from "../../src/stores/playbackSavesSlice";
import { enqueueWrite } from "../../src/stores/writeQueue";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer } from "../support/aFakeServer";
import { aPlaybackSnapshot } from "../support/aPlaybackSnapshot";
import { aTestStore } from "../support/aTestStore";

const EVENTS = "POST /api/watch-events";
const POSITION = "POST /api/playback/entries/entry/position";

it("preserves an unsaved completion for another episode after a newer subject saves", async () => {
  const server = aFakeServer();
  const first = aPlaybackSnapshot({ event: { subject_kind: "episode", subject_id: "episode-one",
    kind: "completed", occurred_at: "2026-09-24T10:00:00Z", position_seconds: 120, runtime_seconds: 120 } });
  const second = aPlaybackSnapshot({ scope: first.scope, fileId: "second-file",
    event: { subject_kind: "episode", subject_id: "episode-two", kind: "progressed",
      occurred_at: "2026-09-24T10:01:00Z", position_seconds: 60, runtime_seconds: 120 } });
  const store = aTestStore();
  server.refuses(EVENTS, 503, { message: "Database offline" });
  await store.dispatch(savePlaybackSnapshot(first));
  server.answers(EVENTS, { id: "newer-event" });
  server.answers(POSITION, aCategoryDetail({ id: first.scope.categoryId, mtime: 2 }));
  await store.dispatch(savePlaybackSnapshot(second));
  expect(store.getState().playbackSaves.jobs[first.id]?.snapshot.event).toEqual(first.event);
  expect(store.getState().ui.toasts.some((toast) => toast.playbackSnapshotId === first.id)).toBe(true);
  server.answers(EVENTS, { id: "recovered-event" });
  server.answers(POSITION, aCategoryDetail({ id: first.scope.categoryId, mtime: 3 }));
  await store.dispatch(savePlaybackSnapshot(first));
  expect(server.requestsFor(EVENTS).at(-1)?.body).toEqual(first.event);
  expect(server.requestsFor(POSITION).at(-1)?.body).toEqual({ watch_event_id: "recovered-event", expected_mtime: 2 });
  expect(store.getState().playbackSaves.jobs).toEqual({});
  expect(store.getState().ui.toasts).toEqual([]);
});

it("serializes event and projection with row edits and replays optimistic patches", async () => {
  const server = aFakeServer();
  const snapshot = aPlaybackSnapshot();
  const id = snapshot.scope.categoryId;
  const store = aTestStore();
  const detail = aCategoryDetail({ id, rows: [{ row: 2, cells: { title: "Original" } }] });
  server.answers(`GET /api/categories/${id}`, detail);
  await store.dispatch(loadCategory(id));
  let release: (reply: { status: number; body: unknown }) => void = () => { throw new Error("No pending projection"); };
  server.answers(EVENTS, { id: "event" });
  server.handles(POSITION, () => new Promise((resolve) => { release = resolve; }));
  const saving = store.dispatch(savePlaybackSnapshot(snapshot));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const patched = { ...detail, mtime: 3, rows: [{ row: 2, cells: { title: "Edited" } }] };
  let rowRelease: (reply: { status: number; body: unknown }) => void = () => { throw new Error("No row write"); };
  server.handles(`PATCH /api/categories/${id}/rows/2`, () => new Promise((resolve) => { rowRelease = resolve; }));
  const writing = store.dispatch(writeRow({ categoryId: id, row: 2, cells: { title: "Edited" }, previous: { title: "Original" } }));
  expect(server.requestsFor(`PATCH /api/categories/${id}/rows/2`)).toHaveLength(0);
  release({ status: 200, body: { ...detail, mtime: 2 } });
  await saving;
  expect(store.getState().category.detail?.rows[0]?.cells.title).toBe("Edited");
  expect(server.requests.at(-1)?.body).toEqual({ cells: { title: "Edited" }, expected_mtime: 2 });
  rowRelease({ status: 200, body: patched });
  await writing;
  expect(store.getState().playbackSaves.jobs).toEqual({});
});

it.each([423, 409])("retains committed event and original projection stamp after %s", async (status) => {
  const server = aFakeServer();
  const snapshot = aPlaybackSnapshot();
  const id = snapshot.scope.categoryId;
  const store = aTestStore();
  server.answers(EVENTS, { id: "durable" });
  server.answers(`GET /api/categories/${id}`, aCategoryDetail({ id, mtime: 8 }));
  server.refuses(POSITION, status, { error: status === 409 ? "StaleWorkbookError" : "WorkbookLockedError", message: "Workbook blocked" });
  await store.dispatch(savePlaybackSnapshot(snapshot));
  expect(store.getState().playbackSaves.jobs[snapshot.id]?.projection).toEqual({ watch_event_id: "durable", expected_mtime: 1 });
  expect(store.getState().ui.toasts[0]?.message).toContain("database; Excel is still pending");
  await enqueueWrite(id, 1, async () => ({ mtime: 9 }));
  server.answers(POSITION, aCategoryDetail({ id, mtime: 10 }));
  await store.dispatch(savePlaybackSnapshot(snapshot));
  expect(server.requestsFor(EVENTS)).toHaveLength(1);
  expect(server.requestsFor(POSITION).map((request) => request.body)).toEqual([
    { watch_event_id: "durable", expected_mtime: 1 }, { watch_event_id: "durable", expected_mtime: 1 },
  ]);
  expect(store.getState().ui.toasts).toEqual([]);
  expect(store.getState().category.detail).toBeNull();
});

it("refreshes a stale category without losing optimistic edits and replaces a repeated failure toast", async () => {
  const server = aFakeServer();
  const snapshot = aPlaybackSnapshot();
  const id = snapshot.scope.categoryId;
  const store = aTestStore();
  const detail = aCategoryDetail({ id });
  store.dispatch(loadCategory.fulfilled(detail, "loaded", id));
  server.answers(EVENTS, { id: "event" });
  server.answers(`GET /api/categories/${id}`, { ...detail, mtime: 8 });
  server.refuses(POSITION, 409, { error: "StaleWorkbookError", message: "Changed" });
  await store.dispatch(savePlaybackSnapshot(snapshot));
  expect(store.getState().category.detail?.mtime).toBe(8);
  await store.dispatch(savePlaybackSnapshot(snapshot));
  expect(store.getState().ui.toasts).toHaveLength(1);
  expect(server.requestsFor(POSITION).at(-1)?.body).toEqual({ watch_event_id: "event", expected_mtime: 1 });
});

it("retries an uncommitted event with the same captured timestamp and no invented saved claim", async () => {
  const server = aFakeServer();
  const snapshot = aPlaybackSnapshot();
  const store = aTestStore();
  server.refuses(EVENTS, 503, { message: "Unavailable" });
  await store.dispatch(savePlaybackSnapshot(snapshot));
  expect(server.requestsFor(POSITION)).toHaveLength(0);
  expect(store.getState().ui.toasts[0]?.message).toContain("could not be saved");
  server.answers(EVENTS, { id: "event" });
  server.answers(POSITION, aCategoryDetail({ id: snapshot.scope.categoryId, mtime: 2 }));
  await store.dispatch(savePlaybackSnapshot(snapshot));
  expect(server.requestsFor(EVENTS).map((request) => request.body)).toEqual([snapshot.event, snapshot.event]);
});

it("deduplicates in-flight retries and skips a committed projection already satisfied by a newer save", async () => {
  const server = aFakeServer();
  const first = aPlaybackSnapshot();
  const second = aPlaybackSnapshot({ scope: first.scope });
  const store = aTestStore();
  server.answers(EVENTS, { id: "event" });
  server.refuses(POSITION, 423, { message: "Locked" });
  const pending = store.dispatch(savePlaybackSnapshot(first));
  await store.dispatch(savePlaybackSnapshot(first));
  await pending;
  expect(server.requestsFor(EVENTS)).toHaveLength(1);
  let unblock: () => void = () => { throw new Error("No queue blocker"); };
  const blocked = enqueueWrite(first.scope.categoryId, 1, () => new Promise<{ mtime: number }>((resolve) => {
    unblock = () => resolve({ mtime: 2 });
  }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const newer = store.dispatch(savePlaybackSnapshot(second));
  const retry = store.dispatch(savePlaybackSnapshot(first));
  server.answers(POSITION, aCategoryDetail({ id: first.scope.categoryId, mtime: 3 }));
  unblock();
  await Promise.all([blocked, retry, newer]);
  expect(server.requestsFor(EVENTS)).toHaveLength(2);
  expect(server.requestsFor(POSITION)).toHaveLength(2);
  expect(store.getState().playbackSaves.jobs).toEqual({});
  expect(store.getState().ui.toasts).toEqual([]);
});

it("ignores stray bookkeeping actions and retains all uncommitted facts, including the same subject", async () => {
  const server = aFakeServer();
  const first = aPlaybackSnapshot();
  const second = aPlaybackSnapshot({ scope: first.scope });
  const store = aTestStore();
  store.dispatch(eventRecorded({ id: "missing", projection: { watch_event_id: "event", expected_mtime: 1 } }));
  store.dispatch(savePlaybackSnapshot.rejected(new Error("Absent"), "absent", aPlaybackSnapshot()));
  server.refuses(EVENTS, 503, { message: "Offline" });
  await store.dispatch(savePlaybackSnapshot(first));
  await store.dispatch(savePlaybackSnapshot(second));
  await store.dispatch(savePlaybackSnapshot(first));
  expect(server.requestsFor(EVENTS)).toHaveLength(3);
  expect(Object.keys(store.getState().playbackSaves.jobs)).toEqual([first.id, second.id]);
});
