import { useState, type ReactElement } from "react";

import { usePlaybackReporter } from "../hooks/usePlaybackReporter";
import type { PlaybackItemRead } from "../types/PlaybackItemRead";
import type { PlaybackScope } from "../types/PlaybackScope";

interface PlaybackVideoProps {
  readonly item: PlaybackItemRead;
  readonly scope: PlaybackScope;
  readonly fileId: string;
}

export function PlaybackVideo({ item, scope, fileId }: PlaybackVideoProps): ReactElement {
  const video = usePlaybackReporter(item, scope, fileId);
  const [failed, setFailed] = useState(false);
  return <>
    <video ref={video} controls preload="none" tabIndex={0} aria-label={`Video for ${scope.title}`}
      src={`/api/playback/${encodeURIComponent(fileId)}/stream`} onError={() => setFailed(true)} />
    {failed && <p role="alert">
      This video could not play. The file may be unavailable or its format unsupported by this browser.
    </p>}
  </>;
}
