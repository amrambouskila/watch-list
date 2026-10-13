import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { fetchEntries } from "../api/fetchEntries";
import { fetchPlaybackItems } from "../api/fetchPlaybackItems";
import type { CuratedEntryRead } from "../types/CuratedEntryRead";
import type { PlaybackItemRead } from "../types/PlaybackItemRead";
import type { LoadStatus } from "./catalogSlice";
import type { WriteFailure } from "./writeFailure";

interface EntriesState {
  categoryId: string | null;
  mtime: number | null;
  items: CuratedEntryRead[];
  status: LoadStatus;
  requestId: string | null;
  error: string | null;
  playback: {
    entryId: string | null;
    items: PlaybackItemRead[];
    status: LoadStatus;
    requestId: string | null;
    error: string | null;
  };
}

const initialState: EntriesState = {
  categoryId: null, mtime: null, items: [], status: "idle", requestId: null, error: null,
  playback: { entryId: null, items: [], status: "idle", requestId: null, error: null },
};

export const loadEntries = createAsyncThunk<
  CuratedEntryRead[], { categoryId: string; mtime: number }, { rejectValue: WriteFailure }
>("entries/load", async ({ categoryId }, { signal, rejectWithValue }) => {
  try {
    return await fetchEntries(categoryId, signal);
  } catch (error) {
    return rejectWithValue({
      message: error instanceof Error ? error.message : "Library availability could not be read.", refreshed: null,
    });
  }
});

export const loadPlaybackItems = createAsyncThunk<PlaybackItemRead[], string, { rejectValue: WriteFailure }>(
  "entries/playback", async (entryId, { signal, rejectWithValue }) => {
    try {
      return await fetchPlaybackItems(entryId, signal);
    } catch (error) {
      return rejectWithValue({
        message: error instanceof Error ? error.message : "Playback items could not be read.", refreshed: null,
      });
    }
  },
);

const entriesSlice = createSlice({
  name: "entries",
  initialState,
  reducers: {
    clearPlayback(state) { state.playback = initialState.playback; },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadEntries.pending, (state, action) => {
        state.categoryId = action.meta.arg.categoryId;
        state.mtime = action.meta.arg.mtime;
        state.requestId = action.meta.requestId;
        state.items = [];
        state.status = "loading";
        state.error = null;
      })
      .addCase(loadEntries.fulfilled, (state, action) => {
        if (state.requestId !== action.meta.requestId) return;
        state.items = action.payload;
        state.status = "ready";
      })
      .addCase(loadEntries.rejected, (state, action) => {
        if (state.requestId !== action.meta.requestId) return;
        state.status = action.meta.aborted ? "idle" : "failed";
        state.error = action.payload?.message ?? null;
      })
      .addCase(loadPlaybackItems.pending, (state, action) => {
        state.playback = {
          entryId: action.meta.arg, items: [], status: "loading", requestId: action.meta.requestId, error: null,
        };
      })
      .addCase(loadPlaybackItems.fulfilled, (state, action) => {
        if (state.playback.requestId !== action.meta.requestId) return;
        state.playback.items = action.payload;
        state.playback.status = "ready";
      })
      .addCase(loadPlaybackItems.rejected, (state, action) => {
        if (state.playback.requestId !== action.meta.requestId) return;
        state.playback.status = action.meta.aborted ? "idle" : "failed";
        state.playback.error = action.payload?.message ?? null;
      });
  },
});

export const { clearPlayback } = entriesSlice.actions;
export default entriesSlice.reducer;
