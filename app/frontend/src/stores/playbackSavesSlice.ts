import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";

import { recordPlaybackEvent } from "../api/recordPlaybackEvent";
import { writePlaybackPosition } from "../api/writePlaybackPosition";
import type { CategoryDetail } from "../types/CategoryDetail";
import type { PlaybackSnapshot } from "../types/PlaybackSnapshot";
import type { PositionWrite } from "../types/PositionWrite";
import type { RootState } from "./store";
import { toWriteFailure, type WriteFailure } from "./writeFailure";
import { enqueueWrite } from "./writeQueue";

interface SaveJob {
  snapshot: PlaybackSnapshot;
  projection: PositionWrite | null;
  status: "saving" | "failed";
}

interface PlaybackSavesState {
  jobs: Record<string, SaveJob>;
}

interface SaveResult {
  mtime: number;
  detail: CategoryDetail | null;
  retired: string[];
}

const initialState: PlaybackSavesState = { jobs: {} };

export const savePlaybackSnapshot = createAsyncThunk<
  SaveResult, PlaybackSnapshot, { state: RootState; rejectValue: WriteFailure }
>("playbackSaves/save", async (snapshot, { dispatch, getState, rejectWithValue }) => {
  const { categoryId, entryId, mtime: seed } = snapshot.scope;
  try {
    return await enqueueWrite(categoryId, seed, async (mtime) => {
      const state = getState().playbackSaves;
      const job = state.jobs[snapshot.id];
      if (job === undefined) {
        return { mtime, detail: null, retired: [snapshot.id] };
      }
      try {
        let projection = job.projection;
        if (projection === null) {
          const event = await recordPlaybackEvent(entryId, snapshot.fileId, snapshot.event);
          projection = { watch_event_id: event.id, expected_mtime: mtime };
          dispatch(eventRecorded({ id: snapshot.id, projection }));
        }
        const detail = await writePlaybackPosition(entryId, projection);
        const retired = Object.values(getState().playbackSaves.jobs)
          .filter((candidate) => candidate.snapshot.scope.entryId === entryId && candidate.projection !== null)
          .map((candidate) => candidate.snapshot.id);
        dispatch(projectionsSaved(retired));
        return { mtime: detail.mtime, detail, retired };
      } catch (error) {
        const failure = await toWriteFailure(error, categoryId);
        const saved = getState().playbackSaves.jobs[snapshot.id]?.projection != null;
        throw { ...failure, playbackSnapshotId: snapshot.id,
          message: `${snapshot.scope.title}: ${saved ? "Progress saved to the database; Excel is still pending." :
            "Playback progress could not be saved."} ${failure.message}` } satisfies WriteFailure;
      }
    });
  } catch (failure) {
    return rejectWithValue(failure as WriteFailure);
  }
}, {
  condition: (snapshot, { getState }) => {
    const state = getState().playbackSaves;
    const job = state.jobs[snapshot.id];
    return job === undefined || job.status === "failed";
  },
});

const playbackSavesSlice = createSlice({
  name: "playbackSaves",
  initialState,
  reducers: {
    projectionsSaved(state, action: PayloadAction<string[]>) {
      for (const id of action.payload) delete state.jobs[id];
    },
    eventRecorded(state, action: PayloadAction<{ id: string; projection: PositionWrite }>) {
      const job = state.jobs[action.payload.id];
      if (job !== undefined) job.projection = action.payload.projection;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(savePlaybackSnapshot.pending, (state, action) => {
      const snapshot = action.meta.arg;
      const job = state.jobs[snapshot.id];
      if (job !== undefined) {
        job.status = "saving";
      } else {
        state.jobs[snapshot.id] = { snapshot, projection: null, status: "saving" };
      }
    });
    builder.addCase(savePlaybackSnapshot.rejected, (state, action) => {
      const job = state.jobs[action.meta.arg.id];
      if (job !== undefined && !action.meta.condition) job.status = "failed";
    });
  },
});

export const { eventRecorded } = playbackSavesSlice.actions;
const { projectionsSaved } = playbackSavesSlice.actions;
export default playbackSavesSlice.reducer;
