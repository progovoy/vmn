/** *text* as a string literal in whichever quote it doesn't contain, or null
 *  when it holds both (the query language has no escapes). */
export function quoteLiteral(text: string): string | null {
  const quote = !text.includes('"') ? '"' : !text.includes("'") ? "'" : null;
  return quote && `${quote}${text}${quote}`;
}

/** The search box as a server query over verstr, note and branch — so it
 *  searches every run, not just the page on screen. The query language has no
 *  escapes, so the text is quoted with whichever quote it doesn't contain; text
 *  holding both can't be expressed and searches the loaded rows only. */
export function searchClause(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  const lit = quoteLiteral(t);
  if (!lit) return null;
  return `verstr ~ ${lit} or note ~ ${lit} or branch ~ ${lit}`;
}

/** The branch filter as a server clause (null for "all branches"). */
export function branchClause(branch: string): string | null {
  const lit = branch ? quoteLiteral(branch) : null;
  return lit && `branch = ${lit}`;
}

/** A typed query and the search clause, ANDed; either may be empty. */
export function combineQueries(query: string, search: string | null): string {
  const q = query.trim();
  if (!search) return q;
  if (!q) return search;
  return `(${q}) and (${search})`;
}

/** The experiment query that matches *text* in a run's verstr or note — what
 *  the run pickers (RunPicker, the command palette) search with. String
 *  literals have no escapes, so pick the quote the text doesn't use. */
export function runSearchQuery(text: string): string {
  const quote = text.includes('"') ? "'" : '"';
  const safe = text.replaceAll(quote, "");
  return `verstr ~ ${quote}${safe}${quote} or note ~ ${quote}${safe}${quote}`;
}
