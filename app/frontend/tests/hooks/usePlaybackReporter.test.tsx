import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { afterEach, expect, it, vi } from "vitest";

import { PlaybackVideo } from "../../src/components/PlaybackVideo";
import { usePlaybackReporter } from "../../src/hooks/usePlaybackReporter";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer } from "../support/aFakeServer";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";
import { aPlaybackSnapshot } from "../support/aPlaybackSnapshot";
import { aTestStore } from "../support/aTestStore";

afterEach(() => { vi.useRealTimers(); });

function playback() {
  vi.useFakeTimers();
  const server = aFakeServer();
  const snapshot = aPlaybackSnapshot();
  const item = aPlaybackItemRead();
  const store = aTestStore();
  server.answers("POST /api/watch-events", { id: "event" });
  server.answers(`POST /api/playback/entries/${snapshot.scope.entryId}/position`,
    aCategoryDetail({ id: snapshot.scope.categoryId, mtime: 2 }));
  const rendered = render(<Provider store={store}><PlaybackVideo item={item} scope={snapshot.scope} fileId="file" /></Provider>);
  const video = screen.getByLabelText<HTMLVideoElement>("Video for A Show");
  Object.defineProperty(video, "duration", { value: 120, configurable: true });
  return { server, snapshot, item, store, video, ...rendered };
}

it("saves both sinks every minute while playing, never at five seconds or before actual playback", async () => {
  const { server, video, unmount } = playback();
  Object.defineProperty(video, "duration", { value: 600 });
  fireEvent.play(video);
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(server.requests).toHaveLength(0);
  fireEvent.pause(video);
  fireEvent.playing(video);
  video.currentTime = 5;
  await act(() => vi.advanceTimersByTimeAsync(5_000));
  expect(server.requests).toHaveLength(0);
  video.currentTime = 60.6;
  await act(() => vi.advanceTimersByTimeAsync(55_000));
  expect(server.requests).toHaveLength(2);
  expect(server.requests[0]?.body).toMatchObject({ kind: "progressed", position_seconds: 61 });
  video.currentTime = 119;
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(server.requests).toHaveLength(4);
  expect(server.requests[2]?.body).toMatchObject({ kind: "progressed" });
  for (const minute of [3, 4, 5]) {
    video.currentTime = minute * 60;
    await act(() => vi.advanceTimersByTimeAsync(60_000));
  }
  expect(server.requests.filter((request) => request.path === "/api/watch-events")).toHaveLength(5);
  expect(server.requests.filter((request) => request.path.endsWith("/position"))).toHaveLength(5);
  unmount();
});

it("keeps the minute deadline when rebuffering or seeking emits repeated playing events", async () => {
  const { server, video, unmount } = playback();
  fireEvent.playing(video);
  for (const position of [15, 30, 45]) {
    video.currentTime = position;
    await act(() => vi.advanceTimersByTimeAsync(15_000));
    fireEvent.playing(video);
  }
  expect(server.requests).toHaveLength(0);
  video.currentTime = 60;
  await act(() => vi.advanceTimersByTimeAsync(15_000));
  expect(server.requests).toHaveLength(2);
  expect(server.requests[0]?.body).toMatchObject({ kind: "progressed", position_seconds: 60 });
  expect(server.requests[1]?.path).toMatch(/\/position$/);
  unmount();
});

it("saves pause once, cancels its timer, and deduplicates close at the same position", async () => {
  const { server, video, unmount } = playback();
  fireEvent.playing(video);
  video.currentTime = 40;
  fireEvent.pause(video);
  await act(() => vi.advanceTimersByTimeAsync(120_000));
  unmount();
  expect(server.requests).toHaveLength(2);
});

it("latches completion before async callbacks and never sends progressed after ended", async () => {
  const { server, video, unmount } = playback();
  fireEvent.playing(video);
  video.currentTime = 120;
  Object.defineProperty(video, "ended", { value: true });
  fireEvent.pause(video);
  fireEvent.ended(video);
  fireEvent.ended(video);
  fireEvent.playing(video);
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(120_000));
  expect(server.requests).toHaveLength(2);
  expect(server.requests[0]?.body).toMatchObject({ kind: "completed", position_seconds: 120, runtime_seconds: 120 });
});

it("never writes on closing a video which was not played", () => {
  const { server, unmount } = playback();
  unmount();
  expect(server.requests).toHaveLength(0);
});

it("restarts reporting when native Replay genuinely starts another watch", async () => {
  const { server, video, unmount } = playback();
  fireEvent.playing(video);
  video.currentTime = 120;
  Object.defineProperty(video, "ended", { value: true, configurable: true });
  fireEvent.ended(video);
  await act(() => vi.advanceTimersByTimeAsync(0));
  video.currentTime = 0;
  Object.defineProperty(video, "ended", { value: false });
  fireEvent.playing(video);
  video.currentTime = 60;
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(server.requests.filter((request) => request.path === "/api/watch-events").map((request) => request.body))
    .toEqual([expect.objectContaining({ kind: "completed", position_seconds: 120 }),
      expect.objectContaining({ kind: "progressed", position_seconds: 60 })]);
  unmount();
});

it("does not deduplicate a separate replay's completion against the previous watch", async () => {
  const { server, video, unmount } = playback();
  fireEvent.playing(video);
  video.currentTime = 120;
  Object.defineProperty(video, "ended", { value: true, configurable: true });
  fireEvent.ended(video);
  await act(() => vi.advanceTimersByTimeAsync(1));
  video.currentTime = 0;
  Object.defineProperty(video, "ended", { value: false, configurable: true });
  fireEvent.playing(video);
  video.currentTime = 120;
  Object.defineProperty(video, "ended", { value: true });
  fireEvent.ended(video);
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(server.requests.filter((request) => request.path === "/api/watch-events")).toHaveLength(2);
});

it("captures the old video and item when selection changes, including shared-file slots", async () => {
  const { server, snapshot, store, item, video, rerender, unmount } = playback();
  fireEvent.playing(video);
  video.currentTime = 40;
  const second = { ...item, id: "second", episode_id: "second-episode" };
  rerender(<Provider store={store}><PlaybackVideo key="second" item={second} scope={snapshot.scope} fileId="file" /></Provider>);
  const secondVideo = screen.getByLabelText<HTMLVideoElement>("Video for A Show");
  Object.defineProperty(secondVideo, "duration", { value: 120 });
  fireEvent.playing(secondVideo);
  secondVideo.currentTime = 70;
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(server.requests.filter((request) => request.path === "/api/watch-events").map((request) => request.body))
    .toEqual([expect.objectContaining({ subject_id: item.episode_id, position_seconds: 40 }),
      expect.objectContaining({ subject_id: second.episode_id, position_seconds: 70 })]);
});

it("surfaces invalid ended timing instead of fabricating a completed event", async () => {
  const { server, store, video, unmount } = playback();
  fireEvent.playing(video);
  video.currentTime = 119;
  fireEvent.ended(video);
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(server.requests).toHaveLength(0);
  expect(store.getState().ui.toasts[0]?.message).toContain("timing is unavailable");
});

it("does not attach a timer without a video node", () => {
  const store = aTestStore();
  const { result } = renderHook(() => usePlaybackReporter(aPlaybackItemRead(), aPlaybackSnapshot().scope, "file"),
    { wrapper: ({ children }) => <Provider store={store}>{children}</Provider> });
  expect(result.current.current).toBeNull();
});
