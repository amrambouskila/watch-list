import { describe, expect, it } from "vitest";

import { clearPlayback, loadEntries, loadPlaybackItems } from "../../src/stores/entriesSlice";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aFakeServer } from "../support/aFakeServer";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";
import { aTestStore } from "../support/aTestStore";

describe("entriesSlice", () => {
  it("rejects stale category success and failure while retaining the current workbook scope", () => {
    const store = aTestStore();
    const old = { categoryId: "old", mtime: 1 };
    const current = { categoryId: "current", mtime: 2 };
    store.dispatch(loadEntries.pending("old-request", old));
    store.dispatch(loadEntries.pending("current-request", current));
    store.dispatch(loadEntries.fulfilled([aCuratedEntryRead()], "old-request", old));
    store.dispatch(loadEntries.rejected(new Error("stale"), "old-request", old));
    expect(store.getState().entries).toMatchObject({ ...current, items: [], status: "loading" });
    store.dispatch(loadEntries.fulfilled([aCuratedEntryRead()], "current-request", current));
    expect(store.getState().entries.status).toBe("ready");
  });

  it("ignores stale playback results, including a request that completes after closing", () => {
    const store = aTestStore();
    store.dispatch(loadPlaybackItems.pending("old", "old-entry"));
    store.dispatch(loadPlaybackItems.pending("current", "current-entry"));
    store.dispatch(loadPlaybackItems.fulfilled([aPlaybackItemRead()], "old", "old-entry"));
    store.dispatch(loadPlaybackItems.rejected(new Error("stale"), "old", "old-entry"));
    expect(store.getState().entries.playback).toMatchObject({ entryId: "current-entry", items: [], status: "loading" });
    store.dispatch(clearPlayback());
    store.dispatch(loadPlaybackItems.fulfilled([aPlaybackItemRead()], "current", "current-entry"));
    expect(store.getState().entries.playback).toMatchObject({ entryId: null, items: [], status: "idle" });
  });

  it("loads category entries with their snapshot scope and playback items with their entry scope", async () => {
    const server = aFakeServer();
    const store = aTestStore();
    server.answers("GET /api/categories/category/entries", [aCuratedEntryRead()]);
    server.answers("GET /api/playback/entries/entry/items", [aPlaybackItemRead()]);
    await store.dispatch(loadEntries({ categoryId: "category", mtime: 3 }));
    await store.dispatch(loadPlaybackItems("entry"));
    expect(store.getState().entries).toMatchObject({ categoryId: "category", mtime: 3, status: "ready" });
    expect(store.getState().entries.playback).toMatchObject({ entryId: "entry", status: "ready" });
  });

  it.each([new Error("Unavailable"), "non-Error rejection"])("reports read failures through the shared toast source: %s", async (failure) => {
    const server = aFakeServer();
    const store = aTestStore();
    server.handles("GET /api/categories/category/entries", () => { throw failure; });
    server.handles("GET /api/playback/entries/entry/items", () => { throw failure; });
    await store.dispatch(loadEntries({ categoryId: "category", mtime: 1 }));
    await store.dispatch(loadPlaybackItems("entry"));
    expect(store.getState().entries.status).toBe("failed");
    expect(store.getState().entries.playback.status).toBe("failed");
    expect(store.getState().ui.toasts).toHaveLength(2);
  });

  it("cancels current loads without reporting an outage", async () => {
    const server = aFakeServer();
    const store = aTestStore();
    server.handles("GET /api/categories/category/entries", () => new Promise(() => {}));
    server.handles("GET /api/playback/entries/entry/items", () => new Promise(() => {}));
    const entries = store.dispatch(loadEntries({ categoryId: "category", mtime: 1 }));
    const playback = store.dispatch(loadPlaybackItems("entry"));
    entries.abort();
    playback.abort();
    await Promise.all([entries, playback]);
    expect(store.getState().entries.status).toBe("idle");
    expect(store.getState().entries.playback.status).toBe("idle");
    expect(store.getState().ui.toasts).toEqual([]);
  });
});
