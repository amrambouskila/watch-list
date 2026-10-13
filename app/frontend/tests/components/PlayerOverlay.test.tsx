import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerOverlay } from "../../src/components/PlayerOverlay";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";
import { aTestStore } from "../support/aTestStore";

const FIRST = aPlaybackItemRead();
const ITEMS = `GET /api/playback/entries/${FIRST.entry_id}/items`;
let server: FakeServer;

beforeEach(() => { server = aFakeServer(); });

describe("PlayerOverlay", () => {
  it("streams only a selected file through the same-origin proxy and shows its actual order", async () => {
    server.answers(ITEMS, [FIRST]);
    const { container } = render(<Provider store={aTestStore()}>
      <PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} />
    </Provider>);
    await screen.findByRole("combobox", { name: "Choose a playback item" });
    const video = container.querySelector("video");
    expect(video).toHaveAttribute("src", `/api/playback/${FIRST.jellyfin_item_id}/stream`);
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("preload", "none");
    expect(screen.getByText("Season 2 · Episode 1 · dvd")).toBeInTheDocument();
    expect(server.requests).toHaveLength(1);
    expect(container.innerHTML).not.toMatch(/api_key|MediaBrowser|8096|https?:\/\//);
    fireEvent.error(video ?? document.createElement("video"));
    expect(screen.getByRole("alert")).toHaveTextContent(/could not play/i);
  });

  it.each(["not_in_library", "ambiguous"] as const)("keeps an initially %s slot selected without silently skipping it", async (availability) => {
    const second = aPlaybackItemRead({ id: "second", position_in_entry: 2, order_label: "Season 2 · Episode 2" });
    server.answers(ITEMS, [{ ...FIRST, availability, jellyfin_item_id: null }, second]);
    const { container } = render(<Provider store={aTestStore()}>
      <PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} />
    </Provider>);
    const select = await screen.findByRole("combobox", { name: "Choose a playback item" });
    expect(select).toHaveValue(FIRST.id);
    expect(container.querySelector("video")).toBeNull();
    expect(screen.getByText(/selected item cannot be played/i)).toBeInTheDocument();
    await userEvent.selectOptions(select, second.id);
    expect(container.querySelector("video")).toHaveAttribute("src", `/api/playback/${second.jellyfin_item_id}/stream`);
  });

  it("retains distinct slots sharing a range file and does not promise episode offsets", async () => {
    server.answers(ITEMS, [
      { ...FIRST, covers_range: true },
      aPlaybackItemRead({ id: "second", position_in_entry: 2, covers_range: true, order_label: "Episode 2" }),
    ]);
    render(<Provider store={aTestStore()}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} /></Provider>);
    const select = await screen.findByRole("combobox", { name: "Choose a playback item" });
    expect(screen.getAllByRole("option")).toHaveLength(2);
    await userEvent.selectOptions(select, "second");
    expect(select).toHaveValue("second");
    expect(screen.getByText(/file covers multiple episodes/i)).toBeInTheDocument();
  });

  it("reports empty queues and errors, then retries through the existing request boundary", async () => {
    server.refuses(ITEMS, 503, { message: "Jellyfin is unavailable" });
    render(<Provider store={aTestStore()}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} /></Provider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Jellyfin is unavailable");
    server.answers(ITEMS, []);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/no playback items/i)).toBeInTheDocument();
  });

  it("closes on Escape or Close, unmounts video and restores the opener's focus", async () => {
    server.answers(ITEMS, [FIRST]);
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const close = vi.fn();
    const rendered = render(<Provider store={aTestStore()}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={close} /></Provider>);
    await screen.findByRole("combobox", { name: "Choose a playback item" });
    const video = screen.getByLabelText("Video for A Show");
    video.focus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Close player" })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(video).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(close).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Close player" }));
    expect(close).toHaveBeenCalledTimes(2);
    rendered.unmount();
    expect(document.querySelector("video")).toBeNull();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("keeps an episode with no known numbering unavailable instead of labelling it as a movie", async () => {
    server.answers(ITEMS, [{ ...FIRST, order_type: null, order_label: "", availability: "not_in_library", jellyfin_item_id: null }]);
    render(<Provider store={aTestStore()}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} /></Provider>);
    expect(await screen.findByText("Numbering unavailable")).toBeInTheDocument();
    expect(screen.getByRole("option")).toHaveTextContent("1. Episode");
    expect(document.querySelector("video")).toBeNull();
  });

  it("shows an order type without a leading separator when its display label is empty", async () => {
    server.answers(ITEMS, [{ ...FIRST, order_type: "absolute", order_label: "" }]);
    render(<Provider store={aTestStore()}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} /></Provider>);
    expect(await screen.findByText("absolute")).toBeInTheDocument();
    expect(screen.queryByText("· absolute")).toBeNull();
  });

  it("cancels a retried load when the overlay closes", async () => {
    server.refuses(ITEMS, 503, { message: "Temporarily unavailable" });
    const store = aTestStore();
    const rendered = render(<Provider store={store}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} /></Provider>);
    await screen.findByRole("alert");
    server.handles(ITEMS, () => new Promise(() => {}));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    rendered.unmount();
    await waitFor(() => expect(store.getState().entries.playback.status).toBe("idle"));
    expect(store.getState().entries.playback.entryId).toBeNull();
    expect(store.getState().ui.toasts).toHaveLength(1);
  });

  it("does not let an old request repaint a different entry", async () => {
    let answer: (reply: { status: number; body: unknown }) => void = () => {};
    server.handles(ITEMS, () => new Promise((resolve) => { answer = resolve; }));
    const other = aPlaybackItemRead({ entry_id: "other-entry", id: "other-item", episode_id: null, movie_title_id: "a-film", order_type: null, order_label: "" });
    server.answers("GET /api/playback/entries/other-entry/items", [other]);
    const store = aTestStore();
    const rendered = render(<Provider store={store}><PlayerOverlay categoryId="playback-test" mtime={1} entryId={FIRST.entry_id} title="A Show" onClose={vi.fn()} /></Provider>);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    rendered.rerender(<Provider store={store}><PlayerOverlay categoryId="playback-test" mtime={1} entryId="other-entry" title="A Film" onClose={vi.fn()} /></Provider>);
    await screen.findByRole("combobox", { name: "Choose a playback item" });
    answer({ status: 200, body: [FIRST] });
    await waitFor(() => expect(store.getState().entries.playback.entryId).toBe("other-entry"));
    expect(screen.getByRole("combobox")).toHaveValue(other.id);
    expect(screen.getByText("Movie")).toBeInTheDocument();
  });
});
