/** One server-sent frame, exactly as the backend writes it. */
export function anSseFrame(event: unknown): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}
