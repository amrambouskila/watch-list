import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { openPlayer } from "../stores/uiSlice";
import type { CuratedEntryRead } from "../types/CuratedEntryRead";

interface PlayButtonProps {
  readonly entry: CuratedEntryRead;
  readonly title: string;
  readonly mtime: number;
}

export function PlayButton({ entry, title, mtime }: PlayButtonProps): ReactElement | null {
  const dispatch = useAppDispatch();
  if (entry.availability !== "in_library") return null;
  return (
    <button
      type="button"
      className="button play-button"
      aria-label={`Play ${title}`}
      onClick={() => dispatch(openPlayer({ entryId: entry.id, title, categoryId: entry.category_slug, mtime }))}
    >
      Play
    </button>
  );
}
