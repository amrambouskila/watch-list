import { configureStore } from "@reduxjs/toolkit";

import catalog from "./catalogSlice";
import category from "./categorySlice";
import chat from "./chatSlice";
import ui from "./uiSlice";

export const store = configureStore({ reducer: { catalog, category, chat, ui } });

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
