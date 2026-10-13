import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { fetchReviewQueue } from "../api/fetchReviewQueue";
import { retryResolution } from "../api/retryResolution";
import { reviewEntry } from "../api/reviewEntry";
import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import type { LoadStatus } from "./catalogSlice";
import type { WriteFailure } from "./writeFailure";

interface ReviewState {
  /** The queue as the backend ordered it: unresolved before least-confident, then category and position. */
  entries: CuratedEntryRead[];
  status: LoadStatus;
  /** Entry ids with a decision or a retry in flight, so a row only ever disables its own controls. */
  busy: string[];
}

const initialState: ReviewState = { entries: [], status: "idle", busy: [] };

/** Neither route carries a workbook mtime, so nothing here can come back refreshed the way a write does. */
function aFailure(error: unknown, fallback: string): WriteFailure {
  return { message: error instanceof Error ? error.message : fallback, refreshed: null };
}

export const loadReviewQueue = createAsyncThunk("review/load", fetchReviewQueue);

export const confirmEntry = createAsyncThunk<CuratedEntryRead, string, { rejectValue: WriteFailure }>(
  "review/confirm",
  async (entryId, { rejectWithValue }) => {
    try {
      return await reviewEntry(entryId, { action: "confirm" });
    } catch (error) {
      return rejectWithValue(aFailure(error, "That row could not be confirmed."));
    }
  },
);

export const retryEntry = createAsyncThunk<CuratedEntryRead, string, { rejectValue: WriteFailure }>(
  "review/retry",
  async (entryId, { rejectWithValue }) => {
    try {
      return await retryResolution(entryId);
    } catch (error) {
      return rejectWithValue(aFailure(error, "That row could not be re-resolved."));
    }
  },
);

function released(busy: string[], entryId: string): string[] {
  return busy.filter((id) => id !== entryId);
}

const reviewSlice = createSlice({
  name: "review",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loadReviewQueue.pending, (state) => {
        // A refresh never blanks a queue that is already on screen, exactly as the catalog's does not.
        state.status = state.entries.length === 0 ? "loading" : "ready";
      })
      .addCase(loadReviewQueue.fulfilled, (state, action) => {
        state.entries = action.payload;
        state.status = "ready";
      })
      .addCase(loadReviewQueue.rejected, (state) => {
        state.status = "failed";
      })
      .addCase(confirmEntry.pending, (state, action) => {
        state.busy.push(action.meta.arg);
      })
      .addCase(confirmEntry.fulfilled, (state, action) => {
        // A confirmed row is no longer one a heuristic left behind, so it leaves the queue it was in.
        state.entries = state.entries.filter((entry) => entry.id !== action.payload.id);
        state.busy = released(state.busy, action.meta.arg);
      })
      .addCase(confirmEntry.rejected, (state, action) => {
        state.busy = released(state.busy, action.meta.arg);
      })
      .addCase(retryEntry.pending, (state, action) => {
        state.busy.push(action.meta.arg);
      })
      .addCase(retryEntry.fulfilled, (state, action) => {
        // A retry answers with the row as it now stands, whichever state that turned out to be: it is
        // still a row a human has not judged, so it keeps its place rather than leaving the queue.
        state.entries = state.entries.map((entry) => (entry.id === action.payload.id ? action.payload : entry));
        state.busy = released(state.busy, action.meta.arg);
      })
      .addCase(retryEntry.rejected, (state, action) => {
        state.busy = released(state.busy, action.meta.arg);
      });
  },
});

export default reviewSlice.reducer;
