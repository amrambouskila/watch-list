import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "../../src/App";
import { UnresolvedView } from "../../src/components/UnresolvedView";
import type { CuratedEntryRead } from "../../src/types/CuratedEntryRead";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aTestStore, type TestStore } from "../support/aTestStore";

const QUEUE = "GET /api/review/entries";
const CATALOG = "GET /api/categories";
const EMPTY_LIBRARY = { categories: [], unreadable: [], shadowed: [], library_dir: "a-library" };
const NEEDS_REVIEW = "Needs review";
const CONFIRM = "Confirm";
const RETRY = "Retry resolution";
const POSITION = "Curated position";
const TRY_AGAIN = "Try again";
/** The backend's own ceiling, mirrored by the api call: 501 rows is two pages, and the second is short. */
const REVIEW_PAGE_SIZE = 500;
/** A note a resolver really writes, and the shape an injected one would take if anything rendered markup. */
const A_SCRIPT_IN_A_NOTE = '<script>alert("resolved")</script>';
const AN_AUTO_NOTE = "TMDB's title matches this row; no release year to check it against";

let server: FakeServer;
let store: TestStore;

function anUnresolvedRow(): CuratedEntryRead {
  return aCuratedEntryRead({
    id: "00000000-0000-4000-8000-0000000000a1",
    position: 4,
    rawTitle: "Marvel One-Shot: The Consultant",
    categorySlug: "marvel-shorts",
    note: "TMDB answered with nothing that matches this row",
    cells: { order: "4", title: "Marvel One-Shot: The Consultant" },
  });
}

function anAutoRow(): CuratedEntryRead {
  return aCuratedEntryRead({
    id: "00000000-0000-4000-8000-0000000000a2",
    position: 9,
    state: "auto",
    confidence: 0.65,
    categorySlug: "one-piece",
    rawTitle: "Dead End Adventure",
    rawUnit: "Season 1",
    note: AN_AUTO_NOTE,
    cells: { order: "9", title: "Dead End Adventure", unit: "Season 1" },
  });
}

/** The queue as the backend really serves it: `?limit=500&offset=n`, a short page ending the walk. */
function serveTheQueue(entries: readonly CuratedEntryRead[]): void {
  server.handles(QUEUE, (asked) => {
    const offset = Number(new URLSearchParams(asked.query).get("offset") ?? "0");
    return { status: 200, body: entries.slice(offset, offset + REVIEW_PAGE_SIZE) };
  });
}

function showTheQueue(entries: readonly CuratedEntryRead[]): void {
  serveTheQueue(entries);
  render(
    <Provider store={store}>
      <UnresolvedView />
    </Provider>,
  );
}

function rowFor(title: string): ReturnType<typeof within> {
  return within(screen.getByRole("listitem", { name: title }));
}

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
});

describe("UnresolvedView", () => {
  it("lists every unresolved and auto entry with its raw cells", async () => {
    showTheQueue([anUnresolvedRow(), anAutoRow()]);

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    const unresolved = rowFor("Marvel One-Shot: The Consultant");
    expect(unresolved.getByText("Unresolved")).toBeInTheDocument();
    expect(unresolved.getByText("TMDB answered with nothing that matches this row")).toBeInTheDocument();
    // Its position in the curated order — the app's own dense index, which is not the `order` cell and
    // is read as text for that reason: this row's sheet happens to spell both of them "4".
    expect(unresolved.getByText(POSITION).parentElement).toHaveTextContent(`${POSITION} 4`);
    // The workbook it came from (R82), and its own verbatim cells keyed as the sheet keys them.
    expect(unresolved.getByText(/marvel-shorts/)).toBeInTheDocument();
    expect(unresolved.getByText("order")).toBeInTheDocument();
    expect(unresolved.getByText("title")).toBeInTheDocument();

    const auto = rowFor("Dead End Adventure");
    // `auto` is not trusted: the state and the number behind it are both on screen.
    expect(auto.getByText(/Auto/)).toBeInTheDocument();
    expect(auto.getByText(/0\.65/)).toBeInTheDocument();
    expect(auto.getByText(AN_AUTO_NOTE)).toBeInTheDocument();
    expect(auto.getByText(POSITION).parentElement).toHaveTextContent(`${POSITION} 9`);
    expect(auto.getByText(/one-piece/)).toBeInTheDocument();
    expect(auto.getByText("unit")).toBeInTheDocument();
    expect(auto.getByText("Season 1")).toBeInTheDocument();
  });

  it("is reachable from the main nav rather than buried in a category", async () => {
    server.answers(CATALOG, EMPTY_LIBRARY);
    serveTheQueue([anUnresolvedRow()]);
    render(
      <Provider store={store}>
        <App />
      </Provider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: NEEDS_REVIEW }));

    expect(store.getState().ui.view).toBe("unresolved");
    await waitFor(() => expect(screen.getAllByRole("listitem")).not.toHaveLength(0));
    expect(screen.getByText("Marvel One-Shot: The Consultant")).toBeInTheDocument();
  });

  it("confirms a row through the review route and takes it out of the queue", async () => {
    const entry = anUnresolvedRow();
    const other = anAutoRow();
    showTheQueue([entry, other]);
    server.answers(`POST /api/review/entries/${entry.id}`, { ...entry, resolution_state: "confirmed" });

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    await userEvent.click(rowFor("Marvel One-Shot: The Consultant").getByRole("button", { name: CONFIRM }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    expect(screen.queryByText("Marvel One-Shot: The Consultant")).not.toBeInTheDocument();
    expect(server.requestsFor(`POST /api/review/entries/${entry.id}`)[0]?.body).toEqual({ action: "confirm" });
  });

  it("renders the note as text, so a note carrying markup is read rather than run", async () => {
    showTheQueue([aCuratedEntryRead({ rawTitle: "A Row", note: A_SCRIPT_IN_A_NOTE })]);

    const note = await screen.findByText(A_SCRIPT_IN_A_NOTE);

    expect(note).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("walks every page, so a queue larger than one page is not silently truncated", async () => {
    // A bootstrap run with no TMDB token leaves all 996 rows unresolved, which is four pages. One
    // request would have shown 500 of them and said nothing about the rest.
    const overflowing = Array.from({ length: REVIEW_PAGE_SIZE + 1 }, (_, index) =>
      aCuratedEntryRead({ id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`, position: index + 1 }),
    );
    showTheQueue(overflowing);

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(REVIEW_PAGE_SIZE + 1));
    expect(server.requestsFor(QUEUE).map((asked) => asked.query)).toEqual([
      `?limit=${REVIEW_PAGE_SIZE}&offset=0`,
      `?limit=${REVIEW_PAGE_SIZE}&offset=${REVIEW_PAGE_SIZE}`,
    ]);
  });

  it("offers a way back when the queue could not be read", async () => {
    server.refuses(QUEUE, 500, { error: "RequestFailed", message: "nothing answered" });
    render(
      <Provider store={store}>
        <UnresolvedView />
      </Provider>,
    );
    await screen.findByText(/could not be read/i);

    serveTheQueue([anUnresolvedRow()]);
    await userEvent.click(screen.getByRole("button", { name: TRY_AGAIN }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    expect(screen.queryByText(/could not be read/i)).not.toBeInTheDocument();
  });

  it("replaces a row's note with the one the retry answered", async () => {
    const entry = anUnresolvedRow();
    showTheQueue([entry]);
    const resolved = "TMDB's title and release year both match this row";
    server.answers(`POST /api/review/entries/${entry.id}/retry`, { ...entry, resolution_note: resolved });

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    await userEvent.click(rowFor("Marvel One-Shot: The Consultant").getByRole("button", { name: RETRY }));

    expect(await screen.findByText(resolved)).toBeInTheDocument();
    expect(screen.queryByText(entry.resolution_note)).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("says the queue is empty rather than rendering nothing", async () => {
    showTheQueue([]);

    expect(await screen.findByText(/nothing is waiting for review/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});
