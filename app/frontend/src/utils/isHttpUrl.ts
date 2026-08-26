const HTTP_PREFIXES: readonly string[] = ["https://", "http://"];

/** Model-supplied text only becomes a link or an image when it is plainly an http(s) address. */
export function isHttpUrl(value: string): boolean {
  return HTTP_PREFIXES.some((prefix) => value.startsWith(prefix));
}
