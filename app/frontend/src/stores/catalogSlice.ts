import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { fetchCatalog } from "../api/fetchCatalog";
import type { CatalogListing } from "../types/CatalogListing";
import { retireWorkbook } from "./categorySlice";

export type LoadStatus = "idle" | "loading" | "ready" | "failed";

interface CatalogState {
  listing: CatalogListing | null;
  status: LoadStatus;
}

const initialState: CatalogState = { listing: null, status: "idle" };

export const loadCatalog = createAsyncThunk("catalog/load", fetchCatalog);

const catalogSlice = createSlice({
  name: "catalog",
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loadCatalog.pending, (state) => {
        state.status = state.listing === null ? "loading" : "ready";
      })
      .addCase(loadCatalog.fulfilled, (state, action) => {
        state.listing = action.payload;
        state.status = "ready";
      })
      .addCase(loadCatalog.rejected, (state) => {
        state.status = "failed";
      })
      // Retiring answers with the library the move left behind, so it is already the fresh listing.
      .addCase(retireWorkbook.fulfilled, (state, action) => {
        state.listing = action.payload;
        state.status = "ready";
      });
  },
});

export default catalogSlice.reducer;
