import { useEffect, useId, useMemo, useState, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { clearPlayback, loadPlaybackItems } from "../stores/entriesSlice";
import { AvailabilityBadge } from "./AvailabilityBadge";
import { PlaybackVideo } from "./PlaybackVideo";

interface PlayerOverlayProps {
  readonly entryId: string;
  readonly title: string;
  readonly categoryId: string;
  readonly mtime: number;
  readonly onClose: () => void;
}

export function PlayerOverlay({ entryId, title, categoryId, mtime, onClose }: PlayerOverlayProps): ReactElement {
  const dispatch = useAppDispatch();
  const playback = useAppSelector((state) => state.entries.playback);
  const panel = useFocusTrap<HTMLDivElement>(onClose);
  const headingId = useId();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const scope = useMemo(() => ({ entryId, title, categoryId, mtime }), [entryId, title, categoryId, mtime]);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setSelectedId(null);
    const pending = dispatch(loadPlaybackItems(entryId));
    return () => {
      pending.abort();
      dispatch(clearPlayback());
    };
  }, [dispatch, entryId, attempt]);

  const items = playback.entryId === entryId ? playback.items : [];
  const selected = items.find((item) => item.id === selectedId) ?? items[0];
  const loading = playback.entryId !== entryId || playback.status === "loading" || playback.status === "idle";
  const fileId = selected?.availability === "in_library" ? selected.jellyfin_item_id : null;

  return (
    <div className="scrim player-scrim" onMouseDown={onClose}>
      <div
        className="player"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        ref={panel}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="player__head">
          <h2 id={headingId}>{title}</h2>
          <button type="button" className="button" aria-label="Close player" onClick={onClose}>
            Close
          </button>
        </header>
        {loading && <p role="status">Loading playback items…</p>}
        {!loading && playback.status === "failed" && (
          <div>
            <p role="alert">{playback.error}</p>
            <button type="button" className="button" onClick={() => setAttempt((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}
        {!loading && playback.status === "ready" && selected === undefined && (
          <p>No playback items are queued for this entry.</p>
        )}
        {selected !== undefined && (
          <>
            <label className="player__selection">
              Choose a playback item
              <select
                aria-label="Choose a playback item"
                value={selected.id}
                onChange={(event) => {
                  setSelectedId(event.target.value);
                }}
              >
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.position_in_entry}. {item.order_label || (item.movie_title_id !== null ? "Movie" : "Episode")}
                  </option>
                ))}
              </select>
            </label>
            <div className="player__context">
              <p>
                {selected.movie_title_id !== null
                  ? "Movie"
                  : [selected.order_label, selected.order_type].filter(Boolean).join(" · ") || "Numbering unavailable"}
              </p>
              <AvailabilityBadge availability={selected.availability} />
            </div>
            {selected.covers_range && (
              <p className="player__hint">
                This file covers multiple episodes; select the position using the native video controls.
              </p>
            )}
            {fileId !== null ? (
              <PlaybackVideo key={selected.id} item={selected} scope={scope} fileId={fileId} />
            ) : (
              <p>The selected item cannot be played. It is missing from the library or needs a pick.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
