import { createSlice, isRejectedWithValue, nanoid, type PayloadAction } from "@reduxjs/toolkit";

import type { AppView } from "../types/AppView";
import type { PlaybackScope } from "../types/PlaybackScope";
import { savePlaybackSnapshot } from "./playbackSavesSlice";
import { removeRow, renameWorkbook, retireWorkbook } from "./categorySlice";

import type { Toast, ToastTone } from "../types/Toast";
import type { WatchFilter } from "../types/WatchFilter";
import type { WriteFailure } from "./writeFailure";

interface UiState {
  view: AppView;
  activeCategoryId: string | null;
  filter: WatchFilter;
  query: string;
  categoryQuery: string;
  expandedRow: number | null;
  referenceOpen: boolean;
  newCategoryOpen: boolean;
  playing: PlaybackScope | null;
  toasts: Toast[];
}

const initialState: UiState = {
  view: "home",
  activeCategoryId: null,
  filter: "all",
  query: "",
  categoryQuery: "",
  expandedRow: null,
  referenceOpen: false,
  newCategoryOpen: false,
  playing: null,
  toasts: [],
};

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    selectCategory(state, action: PayloadAction<string>) {
      state.playing = null;
      state.view = "category";
      state.activeCategoryId = action.payload;
      state.filter = "all";
      state.query = "";
      state.expandedRow = null;
      state.referenceOpen = false;
    },
    goHome(state) {
      state.playing = null;
      state.view = "home";
      state.referenceOpen = false;
    },
    /** The review queue spans every category, so it is a view of its own rather than one category's tab. */
    goToUnresolved(state) {
      state.playing = null;
      state.view = "unresolved";
      state.referenceOpen = false;
    },
    setFilter(state, action: PayloadAction<WatchFilter>) {
      state.filter = action.payload;
    },
    setQuery(state, action: PayloadAction<string>) {
      state.query = action.payload;
    },
    setCategoryQuery(state, action: PayloadAction<string>) {
      state.categoryQuery = action.payload;
    },
    toggleRow(state, action: PayloadAction<number>) {
      state.expandedRow = state.expandedRow === action.payload ? null : action.payload;
    },
    setReferenceOpen(state, action: PayloadAction<boolean>) {
      state.referenceOpen = action.payload;
    },
    setNewCategoryOpen(state, action: PayloadAction<boolean>) {
      state.newCategoryOpen = action.payload;
    },
    openPlayer(state, action: PayloadAction<PlaybackScope>) {
      state.playing = action.payload;
    },
    closePlayer(state) {
      state.playing = null;
    },
    notify(state, action: PayloadAction<{ message: string; tone: ToastTone }>) {
      state.toasts.push({ id: nanoid(), ...action.payload });
    },
    dismissToast(state, action: PayloadAction<string>) {
      state.toasts = state.toasts.filter((toast) => toast.id !== action.payload);
    },
  },
  extraReducers: (builder) => {
    // Row numbers shift up after a delete, so a kept index would open a different entry.
    builder.addCase(removeRow.fulfilled, (state) => {
      state.expandedRow = null;
    });
    // A rename changes the id the filename derives, so the selection has to follow it.
    builder.addCase(renameWorkbook.fulfilled, (state, action) => {
      state.activeCategoryId = action.payload.id;
    });
    // The workbook has left the library, so the category that was open cannot be reopened.
    builder.addCase(retireWorkbook.fulfilled, (state) => {
      state.playing = null;
      state.view = "home";
      state.activeCategoryId = null;
      state.expandedRow = null;
      state.referenceOpen = false;
    });
    builder.addCase(savePlaybackSnapshot.fulfilled, (state, action) => {
      state.toasts = state.toasts.filter((toast) =>
        toast.playbackSnapshotId === undefined || !action.payload.retired.includes(toast.playbackSnapshotId));
    });
    builder.addMatcher(isRejectedWithValue, (state, action) => {
      const failure = action.payload as WriteFailure | undefined;
      if (failure === undefined) return;
      if (failure.playbackSnapshotId !== undefined) {
        state.toasts = state.toasts.filter((toast) => toast.playbackSnapshotId !== failure.playbackSnapshotId);
      }
      state.toasts.push({
        id: nanoid(),
        tone: failure.refreshed ? "info" : "error",
        message: failure.message,
        ...(failure.playbackSnapshotId === undefined ? {} : { playbackSnapshotId: failure.playbackSnapshotId }),
      });
    });
  },
});

export const {
  selectCategory,
  goHome,
  goToUnresolved,
  setFilter,
  setQuery,
  setCategoryQuery,
  toggleRow,
  setReferenceOpen,
  setNewCategoryOpen,
  openPlayer,
  closePlayer,
  notify,
  dismissToast,
} = uiSlice.actions;
export default uiSlice.reducer;
