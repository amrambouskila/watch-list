import type { ReactElement } from "react";

import type { ChatMessage } from "../types/ChatMessage";

interface ChatMessageBubbleProps {
  readonly message: ChatMessage;
}

/** One spoken turn. The text is rendered as text — nothing from the model becomes markup. */
export function ChatMessageBubble({ message }: ChatMessageBubbleProps): ReactElement {
  return <p className={`chat-msg chat-msg--${message.role}`}>{message.text}</p>;
}
