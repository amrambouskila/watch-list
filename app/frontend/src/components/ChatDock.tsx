import { useEffect, useRef, type ReactElement } from "react";

import { useAppDispatch } from "../hooks/useAppDispatch";
import { useAppSelector } from "../hooks/useAppSelector";
import { resetChat, setChatOpen } from "../stores/chatSlice";
import { ChatComposer } from "./ChatComposer";
import { ChatMessageBubble } from "./ChatMessageBubble";
import { ProposalPreview } from "./ProposalPreview";
import { ToolChip } from "./ToolChip";

const COST_DECIMALS = 4;

/** An overlay, not a view: it sits over the cards wall or a category without replacing either. */
export function ChatDock(): ReactElement | null {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.chat.open);
  const status = useAppSelector((state) => state.chat.status);
  const messages = useAppSelector((state) => state.chat.messages);
  const proposal = useAppSelector((state) => state.chat.pendingProposal);
  const cost = useAppSelector((state) => state.chat.lastCostUsd);
  const log = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = log.current;
    if (element !== null) element.scrollTop = element.scrollHeight;
  }, [messages, proposal]);

  if (!open) return null;

  return (
    <aside className={proposal === null ? "chat-dock" : "chat-dock chat-dock--wide"} aria-label="Ask Claude">
      <header className="chat-dock__head">
        <div>
          <span className="eyebrow">Ask Claude</span>
          {cost !== null && <span className="chat-dock__cost mono">${cost.toFixed(COST_DECIMALS)}</span>}
        </div>
        <div className="chat-dock__actions">
          <button
            type="button"
            className="button"
            disabled={status === "streaming"}
            onClick={() => void dispatch(resetChat())}
          >
            New chat
          </button>
          <button type="button" className="button" onClick={() => dispatch(setChatOpen(false))}>
            Close
          </button>
        </div>
      </header>

      <div className="chat-dock__log scroll" ref={log}>
        {messages.length === 0 && (
          <p className="chat-dock__empty">
            Claude researches on the web and hands back a proposal. Nothing is written to a workbook until you
            approve the diff.
          </p>
        )}
        {messages.map((message) =>
          message.role === "tool" ? (
            <ToolChip key={message.id} name={message.tool} detail={message.text} state={message.state} />
          ) : (
            <ChatMessageBubble key={message.id} message={message} />
          ),
        )}
      </div>

      {proposal !== null && <ProposalPreview proposal={proposal} />}

      <ChatComposer />
    </aside>
  );
}
