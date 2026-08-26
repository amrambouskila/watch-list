import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it } from "vitest";

import { ProposalPreview } from "../../src/components/ProposalPreview";
import { loadCatalog } from "../../src/stores/catalogSlice";
import type { CatalogListing } from "../../src/types/CatalogListing";
import type { Proposal } from "../../src/types/Proposal";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer, type FakeServer, type Reply } from "../support/aFakeServer";
import { aHeroCandidate } from "../support/aHeroCandidate";
import { aProposal } from "../support/aProposal";
import { A_CATEGORY_ID, aHeroBody, anEditBody } from "../support/aProposalBody";
import { aRowChange } from "../support/aRowChange";
import { aTestStore, type TestStore } from "../support/aTestStore";

const APPROVE = "POST /api/chat/proposals/a-proposal/approve";
const READ_TARGET = `GET /api/categories/${A_CATEGORY_ID}`;
const READ_LIBRARY = "GET /api/categories";
const WRITTEN_TO = "written-to";

const AN_EDIT = aProposal(
  anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" }, reason: "wrong year" })]),
  { summary: "Correct the year on one entry." },
);

const AN_ARTWORK_OFFER = aProposal(
  aHeroBody([aHeroCandidate(), aHeroCandidate({ source_file: "Other.jpg", url: "not a link at all" })]),
  { summary: "Artwork for the card." },
);

const THE_TARGET_SHEET = aCategoryDetail({
  id: A_CATEGORY_ID,
  name: "The Target",
  rows: [{ row: 2, cells: { title: "The Second", note: "as written" } }],
});

let server: FakeServer;
let store: TestStore;

function show(proposal: Proposal): void {
  render(
    <Provider store={store}>
      <ProposalPreview proposal={proposal} />
    </Provider>,
  );
}

function listingWith(...categories: CatalogListing["categories"]): CatalogListing {
  return { categories, unreadable: [], shadowed: [], library_dir: "a-library" };
}

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
  server.answers(READ_TARGET, THE_TARGET_SHEET);
});

describe("ProposalPreview of an edit", () => {
  it("reads the sheet the edit targets so the diff can say what it would overwrite", async () => {
    show(AN_EDIT);

    expect(await screen.findByTitle("as written → corrected")).toHaveTextContent("as written → corrected");
    expect(screen.getByText("The Second")).toBeInTheDocument();
  });

  it("keeps the approve button out of the part of the proposal that scrolls", async () => {
    show(AN_EDIT);
    const approve = await screen.findByRole("button", { name: "Approve and write" });

    const actions = approve.closest(".proposal__actions");
    const diff = screen.getByRole("group", { name: "Proposed rows" });

    expect(actions).not.toBeNull();
    expect(diff.contains(approve)).toBe(false);
    expect(actions?.parentElement).toBe(diff.parentElement);
  });

  it("writes, clears the proposal and opens the category that was written to", async () => {
    const user = userEvent.setup();
    const written = aCategoryDetail({ id: WRITTEN_TO, name: "Written To" });
    server.answers(APPROVE, written);
    server.answers(READ_LIBRARY, listingWith(written));
    show(AN_EDIT);

    await user.click(await screen.findByRole("button", { name: "Approve and write" }));

    await waitFor(() => {
      expect(store.getState().ui.activeCategoryId).toBe(WRITTEN_TO);
    });
    expect(store.getState().ui.view).toBe("category");
    expect(store.getState().catalog.listing?.categories).toHaveLength(1);
  });

  it("says the write is happening and refuses a second click while it is", async () => {
    const user = userEvent.setup();
    server.handles(APPROVE, () => new Promise<Reply>(() => undefined));
    show(AN_EDIT);

    await user.click(await screen.findByRole("button", { name: "Approve and write" }));

    const writing = await screen.findByRole("button", { name: "Writing…" });
    expect(writing).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeDisabled();
    expect(server.requestsFor(APPROVE)).toHaveLength(1);
  });

  it("writes nothing when the proposal is discarded", async () => {
    const user = userEvent.setup();
    show(AN_EDIT);
    const asked = server.requests.length;

    await user.click(await screen.findByRole("button", { name: "Discard" }));

    expect(store.getState().chat.pendingProposal).toBeNull();
    expect(server.requests).toHaveLength(asked);
  });

  it("links a cited source only when it is plainly an address", async () => {
    show(
      aProposal(anEditBody([aRowChange({ kind: "remove", row: 2 })]), {
        sources: ["https://example.org/the-page", "a note the model wrote instead of a link"],
      }),
    );

    expect(await screen.findByRole("link", { name: "https://example.org/the-page" })).toBeInTheDocument();
    expect(screen.getByText("a note the model wrote instead of a link")).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("says which category is being edited and what the change is meant to do", () => {
    show(AN_EDIT);

    expect(screen.getByText(`Editing · ${A_CATEGORY_ID}`)).toBeInTheDocument();
    expect(screen.getByText("Correct the year on one entry.")).toBeInTheDocument();
  });
});

describe("ProposalPreview of an artwork offer", () => {
  it("offers a pick for each candidate instead of a single approval", () => {
    show(AN_ARTWORK_OFFER);

    expect(screen.getAllByRole("button", { name: "Use this one" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Approve and write" })).toBeNull();
    expect(screen.getByRole("button", { name: "None of these" })).toBeInTheDocument();
  });

  it("names the card a pick would repaint, rather than showing the slug alone", async () => {
    server.answers(READ_LIBRARY, listingWith(aCategoryDetail({ id: A_CATEGORY_ID, name: "The Target" })));
    await store.dispatch(loadCatalog());

    show(AN_ARTWORK_OFFER);

    const target = within(screen.getByRole("region", { name: "The card this artwork would replace" }));
    expect(target.getByText("The Target")).toBeInTheDocument();
    expect(screen.getByText("Artwork · The Target")).toBeInTheDocument();
  });

  it("says plainly when the card a pick would repaint is not in the library listing", () => {
    show(AN_ARTWORK_OFFER);

    expect(screen.getByText("not in the library listing")).toBeInTheDocument();
  });

  it("hands the backend the candidate that was picked", async () => {
    const user = userEvent.setup();
    const repainted = aCategoryDetail({ id: A_CATEGORY_ID, name: "The Target" });
    server.answers("POST /api/chat/proposals/a-proposal/hero/1", repainted);
    server.answers(READ_LIBRARY, listingWith(repainted));
    show(AN_ARTWORK_OFFER);

    await user.click(screen.getAllByRole("button", { name: "Use this one" })[1] as HTMLElement);

    await waitFor(() => {
      expect(server.requestsFor("POST /api/chat/proposals/a-proposal/hero/1")).toHaveLength(1);
    });
    expect(store.getState().chat.messages.map((message) => message.text)).toContain(
      "Artwork saved for The Target.",
    );
  });

  it("keeps the wall of cards up to date rather than navigating away from the chat", async () => {
    const user = userEvent.setup();
    const repainted = aCategoryDetail({ id: A_CATEGORY_ID, name: "The Target" });
    server.answers("POST /api/chat/proposals/a-proposal/hero/0", repainted);
    server.answers(READ_LIBRARY, listingWith(repainted));
    show(AN_ARTWORK_OFFER);

    await user.click(screen.getAllByRole("button", { name: "Use this one" })[0] as HTMLElement);

    await waitFor(() => {
      expect(store.getState().catalog.listing?.categories).toHaveLength(1);
    });
    expect(store.getState().ui.view).toBe("home");
  });
});
