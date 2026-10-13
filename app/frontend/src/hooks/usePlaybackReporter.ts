import { nanoid } from "@reduxjs/toolkit";
import { useEffect, useRef, type MutableRefObject } from "react";

import { savePlaybackSnapshot } from "../stores/playbackSavesSlice";
import { notify } from "../stores/uiSlice";
import type { PlaybackItemRead } from "../types/PlaybackItemRead";
import type { PlaybackScope } from "../types/PlaybackScope";
import { playbackEvent } from "../utils/playbackEvent";
import { useAppDispatch } from "./useAppDispatch";

const SAVE_INTERVAL_MS = 60_000;

export function usePlaybackReporter(
  item: PlaybackItemRead, scope: PlaybackScope, fileId: string,
): MutableRefObject<HTMLVideoElement | null> {
  const video = useRef<HTMLVideoElement | null>(null);
  const dispatch = useAppDispatch();

  useEffect(() => {
    const element = video.current;
    if (element === null) return;
    let played = false;
    let finished = false;
    let previous = "";
    let timer: number | undefined;
    const stopTimer = (): void => { window.clearInterval(timer); timer = undefined; };
    const report = (kind: "progressed" | "completed"): void => {
      if (!played || finished) return;
      if (kind === "completed") finished = true;
      const event = playbackEvent(item, kind, element.currentTime, element.duration, new Date().toISOString());
      if (event === null) {
        dispatch(notify({ tone: "error", message: `${scope.title}: playback timing is unavailable; progress was not saved.` }));
        return;
      }
      const signature = `${kind}:${event.position_seconds}:${event.runtime_seconds}`;
      if (signature === previous) return;
      previous = signature;
      void dispatch(savePlaybackSnapshot({ id: nanoid(), scope, fileId, event }));
    };
    const playing = (): void => {
      played = true;
      if (finished && !element.ended) {
        finished = false;
        previous = "";
      }
      if (!finished && timer === undefined) timer = window.setInterval(() => report("progressed"), SAVE_INTERVAL_MS);
    };
    const pause = (): void => { stopTimer(); if (!element.ended) report("progressed"); };
    const ended = (): void => { stopTimer(); report("completed"); };
    element.addEventListener("playing", playing);
    element.addEventListener("pause", pause);
    element.addEventListener("ended", ended);
    return () => {
      stopTimer();
      element.removeEventListener("playing", playing);
      element.removeEventListener("pause", pause);
      element.removeEventListener("ended", ended);
      report(element.ended ? "completed" : "progressed");
    };
  }, [dispatch, item, scope, fileId]);

  return video;
}
