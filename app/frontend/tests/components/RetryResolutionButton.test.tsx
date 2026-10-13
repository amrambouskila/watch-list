import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it } from "vitest";

import { RetryResolutionButton } from "../../src/components/RetryResolutionButton";
import { loadReviewQueue } from "../../src/stores/reviewSlice";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aTestStore, type TestStore } from "../support/aTestStore";

const QUEUE = "GET /api/review/entries";
const RETRY = "Retry resolution";
const AN_ENTRY_ID = "00000000-0000-4000-8000-0000000000b1";
const RETRY_ROUTE = `POST /api/review/entries/${AN_ENTRY_ID}/retry`;
const A_STALE_NOTE = "TMDB not configured";
const A_FRESH_NOTE = "TMDB's title and release year both match this row";
const A_REFUSAL = "That row is confirmed; correct or reject it rather than re-resolving it.";

let server: FakeServer;
let store: TestStore;

function anUnresolvedRow() {
  return aCuratedEntryRead({ id: AN_ENTRY_ID, rawTitle: "One Piece", note: A_STALE_NOTE });
}

async function showTheButton(): Promise<void> {
  server.answers(QUEUE, [anUnresolvedRow()]);
  await store.dispatch(loadReviewQueue());
  render(
    <Provider store={store}>
      <RetryResolutionButton entryId={AN_ENTRY_ID} />
    </Provider>,
  );
}

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
});

describe("RetryResolutionButton", () => {
  it("posts to the retry route and replaces the row with the answer that came back", async () => {
    await showTheButton();
    server.answers(RETRY_ROUTE, {
      ...anUnresolvedRow(),
      resolution_state: "auto",
      resolution_confidence: 0.95,
      resolution_note: A_FRESH_NOTE,
    });

    await userEvent.click(screen.getByRole("button", { name: RETRY }));

    await waitFor(() => expect(store.getState().review.entries[0]?.resolution_note).toBe(A_FRESH_NOTE));
    expect(server.requestsFor(RETRY_ROUTE)).toHaveLength(1);
    // No body: a retry asks nothing of the reviewer, it asks the provider again on their behalf.
    expect(server.requestsFor(RETRY_ROUTE)[0]?.body).toBeNull();
    expect(store.getState().review.entries).toHaveLength(1);
  });

  it("keeps the row as it was when the retry is refused, and says so", async () => {
    await showTheButton();
    server.refuses(RETRY_ROUTE, 409, { error: "ResolutionConflictError", message: A_REFUSAL });

    await userEvent.click(screen.getByRole("button", { name: RETRY }));

    await waitFor(() => expect(store.getState().ui.toasts.map((toast) => toast.message)).toContain(A_REFUSAL));
    expect(store.getState().review.entries[0]?.resolution_note).toBe(A_STALE_NOTE);
    expect(screen.getByRole("button", { name: RETRY })).toBeEnabled();
  });
});
