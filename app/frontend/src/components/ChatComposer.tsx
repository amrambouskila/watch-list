import { useRef, useState, type KeyboardEvent, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { sendChatMessage } from "../stores/chatSlice";

/** Matches MAX_CHAT_MESSAGE_LENGTH on the backend, so an over-long message is stopped here. */
const MAX_MESSAGE_LENGTH = 16000;
const COMPOSER_ROWS = 3;

export function ChatComposer(): ReactElement {
  const dispatch = useAppDispatch();
  const status = useAppSelector((state) => state.chat.status);
  const [text, setText] = useState("");
  const stop = useRef<(() => void) | null>(null);

  const streaming = status === "streaming";
  const ready = text.trim() !== "" && !streaming;

  const send = (): void => {
    if (!ready) return;
    const run = dispatch(sendChatMessage(text.trim()));
    stop.current = () => run.abort();
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    send();
  };

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <textarea
        className="field composer__field"
        rows={COMPOSER_ROWS}
        maxLength={MAX_MESSAGE_LENGTH}
        value={text}
        placeholder="Build me a chronological WWII movie list"
        aria-label="Message Claude"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="composer__actions">
        <span className="composer__hint">Enter sends · Shift+Enter newline</span>
        {streaming ? (
          <button type="button" className="button" onClick={() => stop.current?.()}>
            Stop
          </button>
        ) : (
          <button type="submit" className="button button--primary" disabled={!ready}>
            Send
          </button>
        )}
      </div>
    </form>
  );
}
