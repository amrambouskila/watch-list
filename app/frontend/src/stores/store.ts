import { configureStore } from "@reduxjs/toolkit";

import catalog from "./catalogSlice";
import category from "./categorySlice";
import chat from "./chatSlice";
import entries from "./entriesSlice";
import playbackSaves from "./playbackSavesSlice";
import review from "./reviewSlice";
import ui from "./uiSlice";

export const store = configureStore({ reducer: { catalog, category, chat, entries, playbackSaves, review, ui } });

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
