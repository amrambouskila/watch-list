import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../../src/App";
import { CategoryStage } from "../../src/components/CategoryStage";
import { loadCategory, writeRow } from "../../src/stores/categorySlice";
import { loadEntries } from "../../src/stores/entriesSlice";
import { savePlaybackSnapshot } from "../../src/stores/playbackSavesSlice";
import { selectCategory } from "../../src/stores/uiSlice";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";
import { aPlaybackSnapshot } from "../support/aPlaybackSnapshot";
import { aTestStore, type TestStore } from "../support/aTestStore";

const ROW = { row: 2, cells: { no: "1", title: "A Show", watched: "" } };
const DETAIL = aCategoryDetail({ rows: [ROW] });
const ENTRY = {
  ...aCuratedEntryRead({ categorySlug: DETAIL.id, cells: ROW.cells }),
  availability: "in_library" as const,
  jellyfin_item_id: "a-series-not-a-file",
};
const ENTRIES = `GET /api/categories/${DETAIL.id}/entries`;
let server: FakeServer;
let store: TestStore;

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
  store.dispatch(selectCategory(DETAIL.id));
  store.dispatch(loadCategory.fulfilled(DETAIL, "loaded", DETAIL.id));
  server.answers(ENTRIES, [ENTRY]);
});

describe("category playback overlay", () => {
  it("flushes the captured video on Close and leaves a usable projection-only retry outside the overlay", async () => {
    server.answers("GET /api/categories", { categories: [DETAIL], unreadable: [], shadowed: [], library_dir: "a-library" });
    server.answers(`GET /api/categories/${DETAIL.id}`, DETAIL);
    const item = aPlaybackItemRead();
    server.answers(`GET /api/playback/entries/${ENTRY.id}/items`, [item]);
    server.answers("POST /api/watch-events", { id: "durable-close" });
    const position = `POST /api/playback/entries/${ENTRY.id}/position`;
    server.refuses(position, 423, { error: "WorkbookLockedError", message: "Close Excel" });
    render(<Provider store={store}><App /></Provider>);
    await userEvent.click(await screen.findByRole("button", { name: "Play A Show" }));
    const video = await screen.findByLabelText<HTMLVideoElement>("Video for A Show");
    Object.defineProperty(video, "duration", { value: 120 });
    fireEvent.playing(video);
    video.currentTime = 90;
    await userEvent.click(screen.getByRole("button", { name: "Close player" }));
    const retry = await screen.findByRole("button", { name: "Retry save" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(server.requestsFor("POST /api/watch-events")[0]?.body)
      .toMatchObject({ subject_id: item.episode_id, position_seconds: 90, kind: "progressed" });
    server.answers(position, { ...DETAIL, mtime: 2 });
    await userEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Retry save" })).toBeNull());
    expect(server.requestsFor("POST /api/watch-events")).toHaveLength(1);
    expect(server.requestsFor(position).map((request) => request.body)).toEqual([
      { watch_event_id: "durable-close", expected_mtime: DETAIL.mtime },
      { watch_event_id: "durable-close", expected_mtime: DETAIL.mtime },
    ]);
  });
  it("protects pending player writes from both workbook and availability refocus refresh", async () => {
    server.answers("GET /api/categories", { categories: [DETAIL], unreadable: [], shadowed: [], library_dir: "a-library" });
    server.answers(`GET /api/categories/${DETAIL.id}`, DETAIL);
    render(<Provider store={store}><App /></Provider>);
    await screen.findByRole("button", { name: "Play A Show" });
    const snapshot = aPlaybackSnapshot();
    act(() => { store.dispatch(savePlaybackSnapshot.pending("player-pending", snapshot)); });
    const before = server.requests.length;
    fireEvent(window, new Event("focus"));
    expect(server.requests).toHaveLength(before);
    act(() => { store.dispatch(savePlaybackSnapshot.rejected(new Error("Failed"), "player-pending", snapshot)); });
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(server.requests.length).toBeGreaterThan(before));
  });
  it("opens the real App player from a matched workbook row and restores that button on close", async () => {
    const item = aPlaybackItemRead();
    server.answers("GET /api/categories", { categories: [DETAIL], unreadable: [], shadowed: [], library_dir: "a-library" });
    server.answers(`GET /api/categories/${DETAIL.id}`, DETAIL);
    server.answers(`GET /api/playback/entries/${ENTRY.id}/items`, [item]);
    const { container } = render(<Provider store={store}><App /></Provider>);

    const play = await screen.findByRole("button", { name: "Play A Show" });
    expect(screen.getByText("In library")).toBeInTheDocument();
    await userEvent.click(play);
    await screen.findByRole("combobox", { name: "Choose a playback item" });
    expect(container.querySelector("video")).toHaveAttribute("src", `/api/playback/${item.jellyfin_item_id}/stream`);
    expect(container.innerHTML).not.toContain("/playback/a-series-not-a-file/stream");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
    expect(play).toHaveFocus();
    expect(server.requests.every((request) => request.method === "GET")).toBe(true);
  });

  it("keeps workbook editing usable when availability fails and offers an explicit retry", async () => {
    server.refuses(ENTRIES, 503, { message: "Projection unavailable" });
    render(<Provider store={store}><CategoryStage /></Provider>);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Edit details for A Show" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play A Show" })).toBeNull();
    server.answers(ENTRIES, [ENTRY]);
    await userEvent.click(screen.getByRole("button", { name: "Retry availability" }));
    expect(await screen.findByRole("button", { name: "Play A Show" })).toBeInTheDocument();
  });

  it("hides the previous snapshot immediately when a workbook's mtime changes", async () => {
    render(<Provider store={store}><CategoryStage /></Provider>);
    await screen.findByRole("button", { name: "Play A Show" });
    server.handles(ENTRIES, () => new Promise(() => {}));
    act(() => { store.dispatch(loadCategory.fulfilled({ ...DETAIL, mtime: 2 }, "changed", DETAIL.id)); });
    expect(screen.queryByRole("button", { name: "Play A Show" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Checking library availability");
  });

  it("never overlays a projection from another active category even while its old workbook is still on screen", async () => {
    render(<Provider store={store}><CategoryStage /></Provider>);
    await screen.findByRole("button", { name: "Play A Show" });
    act(() => { store.dispatch(selectCategory("a-different-category")); });
    expect(screen.queryByRole("button", { name: "Play A Show" })).toBeNull();
  });

  it("leaves an unmatched row unbadged instead of guessing at its availability", async () => {
    server.answers(ENTRIES, [{ ...ENTRY, sheet_row: null }]);
    render(<Provider store={store}><CategoryStage /></Provider>);
    await waitFor(() => expect(store.getState().entries.status).toBe("ready"));
    expect(screen.queryByText("In library")).toBeNull();
    expect(screen.queryByRole("button", { name: "Play A Show" })).toBeNull();
    expect(store.getState().category.detail).toEqual(DETAIL);
  });

  it("does not display a projection loaded for a different workbook mtime", async () => {
    render(<Provider store={store}><CategoryStage /></Provider>);
    await screen.findByRole("button", { name: "Play A Show" });
    act(() => {
      const scope = { categoryId: DETAIL.id, mtime: 99 };
      store.dispatch(loadEntries.pending("stale-snapshot", scope));
      store.dispatch(loadEntries.fulfilled([ENTRY], "stale-snapshot", scope));
    });
    expect(screen.queryByRole("button", { name: "Play A Show" })).toBeNull();
  });

  it("refreshes availability on refocus even when the workbook mtime has not changed", async () => {
    const rendered = render(<Provider store={store}><CategoryStage /></Provider>);
    await screen.findByRole("button", { name: "Play A Show" });
    server.answers(ENTRIES, [{ ...ENTRY, availability: "not_in_library", jellyfin_item_id: null }]);
    fireEvent(window, new Event("focus"));
    expect(await screen.findByText("Opens on your subscription")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play A Show" })).toBeNull();
    expect(store.getState().category.detail?.mtime).toBe(DETAIL.mtime);
    expect(server.requestsFor(ENTRIES)).toHaveLength(2);
    rendered.unmount();
    fireEvent(window, new Event("focus"));
    expect(server.requestsFor(ENTRIES)).toHaveLength(2);
  });

  it("leaves pending workbook writes alone when focus returns", async () => {
    render(<Provider store={store}><CategoryStage /></Provider>);
    await screen.findByRole("button", { name: "Play A Show" });
    const write = { categoryId: DETAIL.id, row: ROW.row, cells: { watched: "Watched" }, previous: { watched: "" } };
    act(() => { store.dispatch(writeRow.pending("pending-write", write)); });
    fireEvent(window, new Event("focus"));
    expect(server.requestsFor(ENTRIES)).toHaveLength(1);
    expect(store.getState().category.pending["pending-write"]).toBeDefined();
    expect(screen.getByRole("button", { name: "Play A Show" })).toBeInTheDocument();
    act(() => { store.dispatch(writeRow.rejected(new Error("Cancelled write"), "pending-write", write)); });
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(server.requestsFor(ENTRIES)).toHaveLength(2));
  });
});
