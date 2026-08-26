import type { ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { setChatOpen } from "../stores/chatSlice";

/** The pull-tab on the right edge that opens the dock. */
export function ChatLauncher(): ReactElement | null {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.chat.open);

  if (open) return null;

  return (
    <button type="button" className="chat-launcher" onClick={() => dispatch(setChatOpen(true))}>
      Ask Claude
    </button>
  );
}
