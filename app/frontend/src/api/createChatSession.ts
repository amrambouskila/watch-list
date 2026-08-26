import { request } from "./request";

interface ChatSessionStarted {
  session_id: string;
}

export async function createChatSession(): Promise<string> {
  const started = await request<ChatSessionStarted>("/api/chat/sessions", { method: "POST" });
  return started.session_id;
}
