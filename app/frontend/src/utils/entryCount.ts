/** How many entries, said the way a person says it. One is an entry; everything else is entries. */
export function entryCount(count: number): string {
  return `${count} ${count === 1 ? "entry" : "entries"}`;
}
