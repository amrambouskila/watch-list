import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyProposal,
  chooseHeroImage,
  proposalDiscarded,
  resetChat,
  sendChatMessage,
} from "../../src/stores/chatSlice";
import type { Proposal } from "../../src/types/Proposal";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aHeroCandidate } from "../support/aHeroCandidate";
import { aProposal } from "../support/aProposal";
import { aHeroBody, anEditBody } from "../support/aProposalBody";
import { aRowChange } from "../support/aRowChange";
import { aTestStore, type TestStore } from "../support/aTestStore";
import { anEventStream, type EventStream } from "../support/anEventStream";
import { anSseFrame } from "../support/anSseFrame";

const SESSION = "a-session";
const OPEN_SESSION = "POST /api/chat/sessions";
const SEND = `POST /api/chat/sessions/${SESSION}/messages`;
const CLOSE_SESSION = `DELETE /api/chat/sessions/${SESSION}`;
const APPROVE = "POST /api/chat/proposals/a-proposal/approve";
const PICK_FIRST = "POST /api/chat/proposals/a-proposal/hero/0";
const DONE = anSseFrame({ type: "done", total_cost_usd: 0.021 });

const AN_EDIT = aProposal(anEditBody([aRowChange({ kind: "revise", row: 2, cells: { note: "corrected" } })]));
const AN_ARTWORK_OFFER = aProposal(aHeroBody([aHeroCandidate(), aHeroCandidate({ source_file: "Other.jpg" })]));

let server: FakeServer;
let store: TestStore;

function openStream(): EventStream {
  const stream = anEventStream();
  server.streams(SEND, stream);
  return stream;
}

async function streamTurn(text: string, frames: readonly string[]): Promise<void> {
  const stream = openStream();
  const run = store.dispatch(sendChatMessage(text));
  for (const frame of frames) stream.push(frame);
  stream.close();
  await run;
}

function transcript(): string[] {
  return store.getState().chat.messages.map((message) => `${message.role}: ${message.text}`);
}

async function withPendingProposal(proposal: Proposal): Promise<void> {
  await streamTurn("a question", [anSseFrame({ type: "proposal", proposal }), DONE]);
}

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
  server.answers(OPEN_SESSION, { session_id: SESSION });
  server.answers(CLOSE_SESSION, null);
});

describe("chatSlice reading a turn", () => {
  it("puts the question in the transcript before Claude has said anything", () => {
    openStream();
    store.dispatch(sendChatMessage("what should I watch"));

    expect(transcript()).toEqual(["you: what should I watch"]);
    expect(store.getState().chat.status).toBe("streaming");
  });

  it("gathers a run of text frames into one thing Claude said", async () => {
    await streamTurn("a question", [
      anSseFrame({ type: "text", text: "Hello " }),
      anSseFrame({ type: "text", text: "there." }),
      DONE,
    ]);

    expect(transcript()).toEqual(["you: a question", "claude: Hello there."]);
  });

  it("starts a new bubble after a tool ran, so the tool is not swallowed by the prose", async () => {
    await streamTurn("a question", [
      anSseFrame({ type: "text", text: "Looking it up." }),
      anSseFrame({ type: "tool", name: "WebSearch", detail: "searching for the release order", state: "running" }),
      anSseFrame({ type: "text", text: "Here is what I found." }),
      DONE,
    ]);

    expect(transcript()).toEqual([
      "you: a question",
      "claude: Looking it up.",
      "tool: searching for the release order",
      "claude: Here is what I found.",
    ]);
    expect(store.getState().chat.messages[2]).toMatchObject({ tool: "WebSearch", state: "running" });
  });

  it("shows the reason Claude gave for an error frame", async () => {
    await streamTurn("a question", [anSseFrame({ type: "error", message: "Claude ran out of turns." }), DONE]);

    expect(transcript()).toEqual(["you: a question", "error: Claude ran out of turns."]);
  });

  it("falls back to the error code, and then to plain words, rather than showing an empty error", async () => {
    await streamTurn("first", [anSseFrame({ type: "error", code: "TurnLimit" }), DONE]);
    await streamTurn("second", [anSseFrame({ type: "error" }), DONE]);

    expect(transcript()).toEqual([
      "you: first",
      "error: TurnLimit",
      "you: second",
      "error: Claude reported an error.",
    ]);
  });

  it("ends the turn on the done frame and records what it cost", async () => {
    await streamTurn("a question", [DONE]);

    expect(store.getState().chat.status).toBe("idle");
    expect(store.getState().chat.lastCostUsd).toBe(0.021);
  });

  it("clears the last turn's cost when the next question is asked", async () => {
    await streamTurn("first", [DONE]);
    openStream();
    store.dispatch(sendChatMessage("second"));

    expect(store.getState().chat.lastCostUsd).toBeNull();
  });

  it("puts the reason in the transcript when the turn never reaches Claude", async () => {
    server.refuses(SEND, 503, { error: "ClaudeUnavailable", message: "The Claude CLI is not installed." });

    await store.dispatch(sendChatMessage("a question"));

    expect(transcript()).toEqual(["you: a question", "error: The Claude CLI is not installed."]);
    expect(store.getState().chat.status).toBe("idle");
  });

  it("says nothing back to the person who pressed Stop", async () => {
    const stream = openStream();
    const run = store.dispatch(sendChatMessage("a question"));
    stream.push(anSseFrame({ type: "text", text: "half an answer" }));
    await vi.waitFor(() => {
      expect(store.getState().chat.messages).toHaveLength(2);
    });

    run.abort();
    await run;

    expect(transcript()).toEqual(["you: a question", "claude: half an answer"]);
    expect(store.getState().chat.status).toBe("idle");
  });
});

describe("chatSlice holding the session", () => {
  it("opens one session and keeps using it", async () => {
    await streamTurn("first", [DONE]);
    await streamTurn("second", [DONE]);

    expect(server.requestsFor(OPEN_SESSION)).toHaveLength(1);
    expect(server.requestsFor(SEND).map((request) => request.body)).toEqual([{ text: "first" }, { text: "second" }]);
  });

  it("closes the session on the server when the chat is reset", async () => {
    await streamTurn("a question", [DONE]);

    await store.dispatch(resetChat());

    expect(server.requestsFor(CLOSE_SESSION)).toHaveLength(1);
    expect(store.getState().chat).toMatchObject({
      sessionId: null,
      messages: [],
      pendingProposal: null,
      status: "idle",
      lastCostUsd: null,
    });
  });

  it("closes the session even when a proposal is still waiting on it", async () => {
    await withPendingProposal(AN_EDIT);

    await store.dispatch(resetChat());

    expect(server.requestsFor(CLOSE_SESSION)).toHaveLength(1);
    expect(store.getState().chat.pendingProposal).toBeNull();
  });

  it("has nothing to close when no session was ever opened", async () => {
    await store.dispatch(resetChat());

    expect(server.requests).toEqual([]);
  });

  it("opens a fresh session for the next question after a reset", async () => {
    await streamTurn("first", [DONE]);
    await store.dispatch(resetChat());
    await streamTurn("second", [DONE]);

    expect(server.requestsFor(OPEN_SESSION)).toHaveLength(2);
  });

  it("cannot have a finished turn brought back by a frame that arrives after the reset", async () => {
    const stream = openStream();
    const run = store.dispatch(sendChatMessage("a question"));
    stream.push(anSseFrame({ type: "text", text: "an answer" }));
    stream.push(DONE);
    await vi.waitFor(() => {
      expect(store.getState().chat.status).toBe("idle");
    });

    await store.dispatch(resetChat());
    stream.push(anSseFrame({ type: "text", text: "a straggler" }));
    stream.close();
    await run;

    expect(transcript()).not.toContain("you: a question");
    expect(transcript()).not.toContain("claude: an answer");
    expect(store.getState().chat.sessionId).toBeNull();
  });
});

describe("chatSlice deciding a proposal's fate", () => {
  it("holds the proposal the stream offered until something decides it", async () => {
    await withPendingProposal(AN_EDIT);

    expect(store.getState().chat.pendingProposal).toEqual(AN_EDIT);
  });

  it("drops a proposal the stream withdrew", async () => {
    await withPendingProposal(AN_EDIT);
    await streamTurn("never mind", [anSseFrame({ type: "proposal" }), DONE]);

    expect(store.getState().chat.pendingProposal).toBeNull();
  });

  it("marks the write as in flight while the workbook is being written", async () => {
    await withPendingProposal(AN_EDIT);
    server.answers(APPROVE, aCategoryDetail({ id: "written-to", name: "Written To" }));

    const run = store.dispatch(applyProposal(AN_EDIT.id));
    expect(store.getState().chat.applying).toBe(true);

    await run;
    expect(store.getState().chat.applying).toBe(false);
  });

  it("notes in the transcript which workbook an approved proposal was written to", async () => {
    await withPendingProposal(AN_EDIT);
    server.answers(APPROVE, aCategoryDetail({ id: "written-to", name: "Written To" }));

    await store.dispatch(applyProposal(AN_EDIT.id));

    expect(transcript().at(-1)).toBe("note: Written to Written To.");
    expect(store.getState().chat.pendingProposal).toBeNull();
  });

  it("keeps the proposal when the write is refused, so it can be approved again", async () => {
    await withPendingProposal(AN_EDIT);
    server.refuses(APPROVE, 409, { error: "StaleWorkbookError", message: "That workbook changed underneath you." });

    await store.dispatch(applyProposal(AN_EDIT.id));

    expect(store.getState().chat.pendingProposal).toEqual(AN_EDIT);
    expect(store.getState().chat.applying).toBe(false);
    expect(transcript().some((line) => line.startsWith("note:"))).toBe(false);
  });

  it("tells the user why a refused write did not happen", async () => {
    await withPendingProposal(AN_EDIT);
    server.refuses(APPROVE, 409, { error: "StaleWorkbookError", message: "That workbook changed underneath you." });

    await store.dispatch(applyProposal(AN_EDIT.id));

    expect(store.getState().ui.toasts.map((toast) => toast.message)).toEqual([
      "That workbook changed underneath you.",
    ]);
  });

  it("notes which card new artwork was saved for", async () => {
    await withPendingProposal(AN_ARTWORK_OFFER);
    server.answers(PICK_FIRST, aCategoryDetail({ id: "repainted", name: "Repainted" }));

    await store.dispatch(chooseHeroImage({ proposalId: AN_ARTWORK_OFFER.id, choice: 0 }));

    expect(transcript().at(-1)).toBe("note: Artwork saved for Repainted.");
    expect(store.getState().chat.pendingProposal).toBeNull();
  });

  it("keeps the candidates on offer when the artwork could not be saved", async () => {
    await withPendingProposal(AN_ARTWORK_OFFER);
    server.refuses(PICK_FIRST, 502, { error: "HeroDownloadError", message: "That image could not be downloaded." });

    await store.dispatch(chooseHeroImage({ proposalId: AN_ARTWORK_OFFER.id, choice: 0 }));

    expect(store.getState().chat.pendingProposal).toEqual(AN_ARTWORK_OFFER);
    expect(store.getState().chat.applying).toBe(false);
  });

  it("writes nothing at all when the proposal is discarded", async () => {
    await withPendingProposal(AN_EDIT);
    const asked = server.requests.length;

    store.dispatch(proposalDiscarded());

    expect(store.getState().chat.pendingProposal).toBeNull();
    expect(server.requests).toHaveLength(asked);
  });
});
