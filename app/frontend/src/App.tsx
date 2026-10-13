import { useEffect, type ReactElement } from "react";

import { CategoryStage } from "./components/CategoryStage";
import { ChatDock } from "./components/ChatDock";
import { ChatLauncher } from "./components/ChatLauncher";
import { HomeView } from "./components/HomeView";
import { NewCategoryDialog } from "./components/NewCategoryDialog";
import { PlayerOverlay } from "./components/PlayerOverlay";
import { Sidebar } from "./components/Sidebar";
import { ToastStack } from "./components/ToastStack";
import { UnresolvedView } from "./components/UnresolvedView";
import { useAppDispatch } from "./hooks/useAppDispatch";
import { useAppSelector } from "./hooks/useAppSelector";
import { loadCatalog } from "./stores/catalogSlice";
import { loadCategory } from "./stores/categorySlice";
import { loadReviewQueue } from "./stores/reviewSlice";
import { hasPendingWrites } from "./stores/hasPendingWrites";
import { closePlayer } from "./stores/uiSlice";

export function App(): ReactElement {
  const dispatch = useAppDispatch();
  const activeId = useAppSelector((state) => state.ui.activeCategoryId);
  const newCategoryOpen = useAppSelector((state) => state.ui.newCategoryOpen);
  const view = useAppSelector((state) => state.ui.view);
  const playing = useAppSelector((state) => state.ui.playing);
  const writing = useAppSelector(hasPendingWrites);

  useEffect(() => {
    void dispatch(loadCatalog());
  }, [dispatch]);

  useEffect(() => {
    if (activeId !== null) void dispatch(loadCategory(activeId));
  }, [activeId, dispatch]);

  /** Coming back to the window picks up anything Excel, the filesystem or an ingest changed meanwhile. */
  useEffect(() => {
    const refresh = (): void => {
      if (writing) return;
      void dispatch(loadCatalog());
      if (activeId !== null) void dispatch(loadCategory(activeId));
      // An ingest run while the window was away is exactly what puts rows into this queue, so the
      // screen showing it is the one that most needs re-reading - and it is only re-read when it is up.
      if (view === "unresolved") void dispatch(loadReviewQueue());
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [activeId, view, writing, dispatch]);

  return (
    <>
      <div className="shell">
        <Sidebar />
        {/* One line per value of `AppView`, so a fourth screen is a line here rather than a nested ternary. */}
        {view === "home" && <HomeView />}
        {view === "unresolved" && <UnresolvedView />}
        {view === "category" && <CategoryStage />}
        {newCategoryOpen && <NewCategoryDialog />}
        <ChatLauncher />
        <ChatDock />
        {playing !== null && (
          <PlayerOverlay
            key={playing.entryId}
            entryId={playing.entryId}
            title={playing.title}
            categoryId={playing.categoryId}
            mtime={playing.mtime}
            onClose={() => dispatch(closePlayer())}
          />
        )}
      </div>
      {/* Outside the shell so no panel that overlays the app can paint over a toast, or it over one. */}
      <ToastStack />
    </>
  );
}
