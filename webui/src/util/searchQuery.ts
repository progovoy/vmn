/** The search box as a server query over verstr, note and branch — so it
 *  searches every run, not just the page on screen. The query language has no
 *  escapes, so the text is quoted with whichever quote it doesn't contain; text
 *  holding both can't be expressed and searches the loaded rows only. */
export function searchClause(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  const quote = !t.includes('"') ? '"' : !t.includes("'") ? "'" : null;
  if (!quote) return null;
  const lit = `${quote}${t}${quote}`;
  return `verstr ~ ${lit} or note ~ ${lit} or branch ~ ${lit}`;
}

/** A typed query and the search clause, ANDed; either may be empty. */
export function combineQueries(query: string, search: string | null): string {
  const q = query.trim();
  if (!search) return q;
  if (!q) return search;
  return `(${q}) and (${search})`;
}
