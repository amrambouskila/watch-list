import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { addWatchColumn } from "../api/addWatchColumn";
import { appendRow } from "../api/appendRow";
import { createCategory, type CategoryDraft } from "../api/createCategory";
import { deleteRow } from "../api/deleteRow";
import { fetchCategory } from "../api/fetchCategory";
import { renameCategory } from "../api/renameCategory";
import { retireCategory } from "../api/retireCategory";
import { updateRow } from "../api/updateRow";
import type { CatalogListing } from "../types/CatalogListing";
import type { CategoryDetail } from "../types/CategoryDetail";
import type { LoadStatus } from "./catalogSlice";
import { applyProposal } from "./chatSlice";
import type { RootState } from "./store";
import { toWriteFailure, type WriteFailure } from "./writeFailure";
import { enqueueWrite, noteMtime } from "./writeQueue";

/** A row edit painted on screen but not yet acknowledged by the server. */
interface PendingPatch {
  categoryId: string;
  row: number;
  cells: Record<string, string>;
}

interface CategoryState {
  detail: CategoryDetail | null;
  status: LoadStatus;
  /** Keyed by thunk requestId; several writes can be queued at once. */
  pending: Record<string, PendingPatch>;
}

const initialState: CategoryState = { detail: null, status: "idle", pending: {} };

const GONE: WriteFailure = { message: "That category is no longer open.", refreshed: null };

/** The mtime as of right now, not as of when the click happened. */
function freshMtime(state: RootState, categoryId: string): number | null {
  const detail = state.category.detail;
  return detail !== null && detail.id === categoryId ? detail.mtime : null;
}

type WriteConfig = { state: RootState; rejectValue: WriteFailure };
type Reject = (failure: WriteFailure) => unknown;

/** Queue one write behind the others for this workbook and turn any failure into a WriteFailure. */
function runWrite(
  categoryId: string,
  state: RootState,
  reject: Reject,
  call: (mtime: number) => Promise<CategoryDetail>,
): Promise<CategoryDetail> {
  const seed = freshMtime(state, categoryId);
  if (seed === null) return reject(GONE) as Promise<CategoryDetail>;
  return enqueueWrite(categoryId, seed, async (mtime) => {
    try {
      return await call(mtime);
    } catch (error) {
      throw await toWriteFailure(error, categoryId);
    }
  }).catch((failure: WriteFailure) => reject(failure) as CategoryDetail);
}

export const loadCategory = createAsyncThunk<CategoryDetail, string, { rejectValue: WriteFailure }>(
  "category/load",
  async (categoryId, { rejectWithValue }) => {
    try {
      const detail = await fetchCategory(categoryId);
      noteMtime(categoryId, detail.mtime);
      return detail;
    } catch (error) {
      const message = error instanceof Error ? error.message : "That category could not be opened.";
      return rejectWithValue({ message, refreshed: null });
    }
  },
);

export const writeRow = createAsyncThunk<
  CategoryDetail,
  {
    categoryId: string;
    row: number;
    cells: Record<string, string>;
    /** Values to restore if the save fails, so the optimistic paint can be undone. */
    previous: Record<string, string>;
  },
  WriteConfig
>("category/writeRow", (arg, { getState, rejectWithValue }) =>
  runWrite(arg.categoryId, getState(), rejectWithValue, (mtime) => updateRow(arg.categoryId, arg.row, arg.cells, mtime)),
);

export const addRow = createAsyncThunk<
  CategoryDetail,
  { categoryId: string; cells: Record<string, string> },
  WriteConfig
>("category/addRow", (arg, { getState, rejectWithValue }) =>
  runWrite(arg.categoryId, getState(), rejectWithValue, (mtime) => appendRow(arg.categoryId, arg.cells, mtime)),
);

export const removeRow = createAsyncThunk<CategoryDetail, { categoryId: string; row: number }, WriteConfig>(
  "category/removeRow",
  (arg, { getState, rejectWithValue }) =>
    runWrite(arg.categoryId, getState(), rejectWithValue, (mtime) => deleteRow(arg.categoryId, arg.row, mtime)),
);

export const enableWatchColumn = createAsyncThunk<CategoryDetail, { categoryId: string }, WriteConfig>(
  "category/enableWatchColumn",
  (arg, { getState, rejectWithValue }) =>
    runWrite(arg.categoryId, getState(), rejectWithValue, (mtime) => addWatchColumn(arg.categoryId, mtime)),
);

/**
 * Renaming rewrites the filename, and the category id is derived from it — so unlike every
 * other write, this one comes back with a different id than it went out with.
 */
export const renameWorkbook = createAsyncThunk<
  CategoryDetail,
  { categoryId: string; stem: string },
  WriteConfig
>("category/rename", (arg, { getState, rejectWithValue }) =>
  runWrite(arg.categoryId, getState(), rejectWithValue, (mtime) =>
    renameCategory(arg.categoryId, arg.stem, mtime),
  ),
);

/**
 * Retiring moves the workbook out of the library, so unlike every other write it answers with the
 * library that is left: there is no longer a category to come back with.
 *
 * It is deliberately not queued behind the other writes — the queue threads each response's mtime
 * into the next request, and this response carries none. A write still in flight therefore leaves
 * the stamp on screen stale, and the server refuses the retire rather than acting on a stale click.
 */
export const retireWorkbook = createAsyncThunk<CatalogListing, { categoryId: string }, WriteConfig>(
  "category/retire",
  async (arg, { getState, rejectWithValue }) => {
    const mtime = freshMtime(getState(), arg.categoryId);
    if (mtime === null) return rejectWithValue(GONE);
    try {
      return await retireCategory(arg.categoryId, mtime);
    } catch (error) {
      return rejectWithValue(await toWriteFailure(error, arg.categoryId));
    }
  },
);

export const addCategory = createAsyncThunk<CategoryDetail, CategoryDraft, { rejectValue: WriteFailure }>(
  "category/addCategory",
  async (draft, { rejectWithValue }) => {
    try {
      return await createCategory(draft);
    } catch (error) {
      const message = error instanceof Error ? error.message : "That category was not created.";
      return rejectWithValue({ message, refreshed: null });
    }
  },
);

function patchRow(detail: CategoryDetail, row: number, cells: Record<string, string>): CategoryDetail {
  return {
    ...detail,
    rows: detail.rows.map((entry) => (entry.row === row ? { ...entry, cells: { ...entry.cells, ...cells } } : entry)),
  };
}

/**
 * Re-apply every edit still in flight on top of a server response.
 *
 * Writes are queued, so an earlier response arrives while later edits are already on screen.
 * Without this, the rows behind it would repaint with their pre-edit values until their own
 * write landed.
 */
function withPending(detail: CategoryDetail, pending: Record<string, PendingPatch>): CategoryDetail {
  return Object.values(pending)
    .filter((patch) => patch.categoryId === detail.id)
    .reduce((current, patch) => patchRow(current, patch.row, patch.cells), detail);
}

const categorySlice = createSlice({
  name: "category",
  initialState,
  reducers: {
    clear(state) {
      state.detail = null;
      state.status = "idle";
      state.pending = {};
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadCategory.pending, (state, action) => {
        state.status = state.detail?.id === action.meta.arg ? "ready" : "loading";
      })
      .addCase(loadCategory.fulfilled, (state, action) => {
        if (action.payload.id !== action.meta.arg) return;
        state.detail = withPending(action.payload, state.pending);
        state.status = "ready";
      })
      .addCase(loadCategory.rejected, (state, action) => {
        if (state.detail !== null && state.detail.id !== action.meta.arg) return;
        state.status = "failed";
        state.detail = null;
      })
      .addCase(writeRow.pending, (state, action) => {
        const { categoryId, row, cells } = action.meta.arg;
        state.pending[action.meta.requestId] = { categoryId, row, cells };
        if (state.detail?.id === categoryId) state.detail = patchRow(state.detail, row, cells);
      })
      .addCase(writeRow.rejected, (state, action) => {
        delete state.pending[action.meta.requestId];
        const { categoryId, row, previous } = action.meta.arg;
        const refreshed = action.payload?.refreshed;
        if (refreshed && refreshed.id === categoryId) {
          state.detail = withPending(refreshed, state.pending);
        } else if (state.detail?.id === categoryId) {
          state.detail = withPending(patchRow(state.detail, row, previous), state.pending);
        }
      });

    builder
      .addCase(retireWorkbook.fulfilled, (state) => {
        state.detail = null;
        state.status = "idle";
        state.pending = {};
      })
      .addCase(retireWorkbook.rejected, (state, action) => {
        const refreshed = action.payload?.refreshed;
        if (refreshed && refreshed.id === action.meta.arg.categoryId) {
          state.detail = withPending(refreshed, state.pending);
        }
      });

    builder
      .addCase(renameWorkbook.fulfilled, (state, action) => {
        noteMtime(action.payload.id, action.payload.mtime);
        state.detail = action.payload;
        state.status = "ready";
        state.pending = {};
      })
      .addCase(renameWorkbook.rejected, (state, action) => {
        const refreshed = action.payload?.refreshed;
        if (refreshed && refreshed.id === action.meta.arg.categoryId) {
          state.detail = withPending(refreshed, state.pending);
        }
      });

    for (const thunk of [addRow, removeRow, enableWatchColumn]) {
      builder.addCase(thunk.rejected, (state, action) => {
        const refreshed = action.payload?.refreshed;
        if (refreshed && refreshed.id === action.meta.arg.categoryId) {
          state.detail = withPending(refreshed, state.pending);
        }
      });
    }

    // An approved proposal answers with the workbook as it now stands. Recording its mtime keeps the
    // next click from sending the stamp the write just spent, and painting it keeps that write from
    // being invisible: selecting the category already on screen re-fires no load.
    builder.addCase(applyProposal.fulfilled, (state, action) => {
      noteMtime(action.payload.id, action.payload.mtime);
      if (state.detail?.id !== action.payload.id) return;
      state.detail = withPending(action.payload, state.pending);
      state.status = "ready";
    });

    for (const thunk of [writeRow, addRow, removeRow, enableWatchColumn]) {
      builder.addCase(thunk.fulfilled, (state, action) => {
        delete state.pending[action.meta.requestId];
        if (action.payload.id !== action.meta.arg.categoryId) return;
        state.detail = withPending(action.payload, state.pending);
        state.status = "ready";
      });
    }
  },
});

export const { clear } = categorySlice.actions;
export default categorySlice.reducer;
