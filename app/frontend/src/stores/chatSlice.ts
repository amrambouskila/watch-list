import { createAsyncThunk, createSlice, nanoid, type PayloadAction } from "@reduxjs/toolkit";

import { approveProposal } from "../api/approveProposal";
import { chooseHero } from "../api/chooseHero";
import { createChatSession } from "../api/createChatSession";
import { discardProposal } from "../api/discardProposal";
import { openChatStream } from "../api/openChatStream";
import type { CategoryDetail } from "../types/CategoryDetail";
import type { ChatEvent } from "../types/ChatEvent";
import type { ChatMessage, ChatMessageRole } from "../types/ChatMessage";
import type { Proposal } from "../types/Proposal";
import type { RootState } from "./store";
import type { WriteFailure } from "./writeFailure";

export type ChatStatus = "idle" | "streaming";

interface ChatState {
  open: boolean;
  sessionId: string | null;
  status: ChatStatus;
  messages: ChatMessage[];
  pendingProposal: Proposal | null;
  applying: boolean;
  /** What the last finished turn cost, from its done frame. */
  lastCostUsd: number | null;
}

const initialState: ChatState = {
  open: false,
  sessionId: null,
  status: "idle",
  messages: [],
  pendingProposal: null,
  applying: false,
  lastCostUsd: null,
};

const STREAM_FAILED = "That message did not reach Claude.";
const APPLY_FAILED = "That proposal was not applied.";
const HERO_FAILED = "That artwork was not saved.";
const UNNAMED_ERROR = "Claude reported an error.";

/** Which candidate of which pending proposal the user picked by eye. */
interface HeroChoice {
  proposalId: string;
  choice: number;
}

function transcriptEntry(role: ChatMessageRole, text: string): ChatMessage {
  return { id: nanoid(), role, text, tool: "", state: "" };
}

function writeStarted(state: ChatState): void {
  state.applying = true;
}

function writeFinished(state: ChatState, note: string): void {
  state.applying = false;
  state.pendingProposal = null;
  state.messages.push(transcriptEntry("note", note));
}

/** The proposal is kept: a locked or changed workbook is retried, not lost. */
function writeFailed(state: ChatState): void {
  state.applying = false;
}

/** Text arrives as deltas, so a run of them belongs to one bubble. */
function appendSpokenText(state: ChatState, text: string): void {
  const last = state.messages[state.messages.length - 1];
  if (last !== undefined && last.role === "claude") last.text += text;
  else state.messages.push(transcriptEntry("claude", text));
}

export const sendChatMessage = createAsyncThunk<void, string, { state: RootState }>(
  "chat/send",
  async (text, { dispatch, getState, signal }) => {
    const existing = getState().chat.sessionId;
    const sessionId = existing ?? (await createChatSession());
    if (existing === null) dispatch(sessionOpened(sessionId));
    await openChatStream(sessionId, text, signal, (event) => void dispatch(frameReceived(event)));
  },
);

export const applyProposal = createAsyncThunk<CategoryDetail, string, { rejectValue: WriteFailure }>(
  "chat/applyProposal",
  async (proposalId, { rejectWithValue }) => {
    try {
      return await approveProposal(proposalId);
    } catch (error) {
      const message = error instanceof Error ? error.message : APPLY_FAILED;
      return rejectWithValue({ message, refreshed: null });
    }
  },
);

export const chooseHeroImage = createAsyncThunk<CategoryDetail, HeroChoice, { rejectValue: WriteFailure }>(
  "chat/chooseHero",
  async ({ proposalId, choice }, { rejectWithValue }) => {
    try {
      return await chooseHero(proposalId, choice);
    } catch (error) {
      const message = error instanceof Error ? error.message : HERO_FAILED;
      return rejectWithValue({ message, refreshed: null });
    }
  },
);

export const resetChat = createAsyncThunk<void, void, { state: RootState }>(
  "chat/reset",
  async (_, { dispatch, getState }) => {
    // Read the id before clearing. A `pending` reducer runs before this does, so clearing there
    // would leave nothing to close and the CLI subprocess would live on to its idle eviction.
    const { sessionId } = getState().chat;
    dispatch(chatCleared());
    if (sessionId !== null) await discardProposal(sessionId);
  },
);

const chatSlice = createSlice({
  name: "chat",
  initialState,
  reducers: {
    setChatOpen(state, action: PayloadAction<boolean>) {
      state.open = action.payload;
    },
    sessionOpened(state, action: PayloadAction<string>) {
      state.sessionId = action.payload;
    },
    proposalDiscarded(state) {
      state.pendingProposal = null;
    },
    chatCleared(state) {
      state.sessionId = null;
      state.messages = [];
      state.pendingProposal = null;
      state.status = "idle";
      state.lastCostUsd = null;
    },
    frameReceived(state, action: PayloadAction<ChatEvent>) {
      const event = action.payload;
      switch (event.type) {
        case "text":
          appendSpokenText(state, event.text ?? "");
          return;
        case "tool":
          state.messages.push({
            id: nanoid(),
            role: "tool",
            text: event.detail ?? "",
            tool: event.name ?? "",
            state: event.state ?? "",
          });
          return;
        case "proposal":
          state.pendingProposal = event.proposal ?? null;
          return;
        case "error":
          state.messages.push(transcriptEntry("error", event.message ?? event.code ?? UNNAMED_ERROR));
          return;
        case "done":
          state.status = "idle";
          state.lastCostUsd = event.total_cost_usd ?? null;
          return;
      }
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(sendChatMessage.pending, (state, action) => {
        state.messages.push(transcriptEntry("you", action.meta.arg));
        state.status = "streaming";
        state.lastCostUsd = null;
      })
      .addCase(sendChatMessage.fulfilled, (state) => {
        state.status = "idle";
      })
      .addCase(sendChatMessage.rejected, (state, action) => {
        state.status = "idle";
        // An abort is the Stop button, which needs no explaining back to the person who pressed it.
        if (action.meta.aborted) return;
        state.messages.push(transcriptEntry("error", action.error.message ?? STREAM_FAILED));
      });

    builder
      .addCase(applyProposal.pending, writeStarted)
      .addCase(applyProposal.fulfilled, (state, action) => {
        writeFinished(state, `Written to ${action.payload.name}.`);
      })
      .addCase(applyProposal.rejected, writeFailed)
      .addCase(chooseHeroImage.pending, writeStarted)
      .addCase(chooseHeroImage.fulfilled, (state, action) => {
        writeFinished(state, `Artwork saved for ${action.payload.name}.`);
      })
      .addCase(chooseHeroImage.rejected, writeFailed);
  },
});

const { sessionOpened, frameReceived, chatCleared } = chatSlice.actions;

export const { setChatOpen, proposalDiscarded } = chatSlice.actions;
export default chatSlice.reducer;
