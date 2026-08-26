import { useEffect, type ReactElement } from "react";

import { CategoryStage } from "./components/CategoryStage";
import { ChatDock } from "./components/ChatDock";
import { ChatLauncher } from "./components/ChatLauncher";
import { HomeView } from "./components/HomeView";
import { NewCategoryDialog } from "./components/NewCategoryDialog";
import { Sidebar } from "./components/Sidebar";
import { ToastStack } from "./components/ToastStack";
import { useAppDispatch } from "./hooks/useAppDispatch";
import { useAppSelector } from "./hooks/useAppSelector";
import { loadCatalog } from "./stores/catalogSlice";
import { loadCategory } from "./stores/categorySlice";

export function App(): ReactElement {
  const dispatch = useAppDispatch();
  const activeId = useAppSelector((state) => state.ui.activeCategoryId);
  const newCategoryOpen = useAppSelector((state) => state.ui.newCategoryOpen);
  const view = useAppSelector((state) => state.ui.view);
  const writing = useAppSelector((state) => Object.keys(state.category.pending).length > 0);

  useEffect(() => {
    void dispatch(loadCatalog());
  }, [dispatch]);

  useEffect(() => {
    if (activeId !== null) void dispatch(loadCategory(activeId));
  }, [activeId, dispatch]);

  /** Coming back to the window picks up anything Excel or the filesystem changed meanwhile. */
  useEffect(() => {
    const refresh = (): void => {
      if (writing) return;
      void dispatch(loadCatalog());
      if (activeId !== null) void dispatch(loadCategory(activeId));
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [activeId, writing, dispatch]);

  return (
    <>
      <div className="shell">
        <Sidebar />
        {view === "home" ? <HomeView /> : <CategoryStage />}
        {newCategoryOpen && <NewCategoryDialog />}
        <ChatLauncher />
        <ChatDock />
      </div>
      {/* Outside the shell so no panel that overlays the app can paint over a toast, or it over one. */}
      <ToastStack />
    </>
  );
}
