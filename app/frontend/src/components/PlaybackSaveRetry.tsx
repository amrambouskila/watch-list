import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { savePlaybackSnapshot } from "../stores/playbackSavesSlice";

interface PlaybackSaveRetryProps { readonly snapshotId: string }

export function PlaybackSaveRetry({ snapshotId }: PlaybackSaveRetryProps): ReactElement | null {
  const dispatch = useAppDispatch();
  const job = useAppSelector((state) => state.playbackSaves.jobs[snapshotId]);
  if (job === undefined) return null;
  return <button type="button" className="button" disabled={job.status === "saving"}
      onClick={() => void dispatch(savePlaybackSnapshot(job.snapshot))}>
      {job.status === "saving" ? "Saving…" : "Retry save"}
    </button>;
}
