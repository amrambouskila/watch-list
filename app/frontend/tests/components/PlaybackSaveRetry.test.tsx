import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { afterEach, expect, it, vi } from "vitest";

import { PlaybackSaveRetry } from "../../src/components/PlaybackSaveRetry";
import { ToastStack } from "../../src/components/ToastStack";
import { savePlaybackSnapshot } from "../../src/stores/playbackSavesSlice";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer } from "../support/aFakeServer";
import { aPlaybackSnapshot } from "../support/aPlaybackSnapshot";
import { aTestStore } from "../support/aTestStore";

afterEach(() => { vi.useRealTimers(); });

it("keeps a failed final save available after the overlay closes and retries only Excel", async () => {
  const store = aTestStore();
  const server = aFakeServer();
  const snapshot = aPlaybackSnapshot();
  server.answers("POST /api/watch-events", { id: "committed" });
  const route = `POST /api/playback/entries/${snapshot.scope.entryId}/position`;
  server.refuses(route, 423, { message: "Close Excel to save" });
  await store.dispatch(savePlaybackSnapshot(snapshot));
  vi.useFakeTimers();
  render(<Provider store={store}><ToastStack /></Provider>);
  await act(() => vi.advanceTimersByTimeAsync(120_000));
  expect(screen.getByRole("button", { name: "Retry save" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("database; Excel is still pending");
  vi.useRealTimers();
  let release: (response: { status: number; body: unknown }) => void = () => { throw new Error("No retry"); };
  server.handles(route, () => new Promise((resolve) => { release = resolve; }));
  await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
  expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await act(async () => {
    release({ status: 200, body: aCategoryDetail({ id: snapshot.scope.categoryId, mtime: 2 }) });
  });
  expect(screen.queryByRole("button", { name: "Retry save" })).toBeNull();
  expect(server.requestsFor("POST /api/watch-events")).toHaveLength(1);
});

it("keeps older unsaved facts retryable and tolerates a removed save job", async () => {
  const store = aTestStore();
  const server = aFakeServer();
  const first = aPlaybackSnapshot();
  const second = aPlaybackSnapshot({ scope: first.scope });
  server.refuses("POST /api/watch-events", 503, { message: "Offline" });
  await store.dispatch(savePlaybackSnapshot(first));
  await store.dispatch(savePlaybackSnapshot(second));
  render(<Provider store={store}><PlaybackSaveRetry snapshotId={first.id} /><PlaybackSaveRetry snapshotId="absent" /></Provider>);
  expect(screen.getByRole("button", { name: "Retry save" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry save" }));
  expect(server.requestsFor("POST /api/watch-events")).toHaveLength(3);
});
