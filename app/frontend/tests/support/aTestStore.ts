import { configureStore } from "@reduxjs/toolkit";

import catalog from "../../src/stores/catalogSlice";
import category from "../../src/stores/categorySlice";
import chat from "../../src/stores/chatSlice";
import ui from "../../src/stores/uiSlice";

/** The app's real reducers in a store of their own, so no test inherits another test's state. */
export function aTestStore() {
  return configureStore({ reducer: { catalog, category, chat, ui } });
}

export type TestStore = ReturnType<typeof aTestStore>;
