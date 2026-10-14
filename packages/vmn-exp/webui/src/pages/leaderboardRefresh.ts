import { verstrInQuery } from "../util/searchQuery";
import { stabilizeRows } from "../util/stableRows";

type Page<R> = { rows: R[]; total: number; next_cursor?: string | null };

/** A held refresh's news (plan 23 W6): rows of the first page not on screen,
 *  and whether the first page's held rows changed order. */
export type HeldChange = { added: number; reordered: boolean };

/** Verstrs per by-id request — keeps the query (and its URL) bounded. */
const VERSTR_CHUNK = 200;

export function chunk<T>(items: readonly T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += n) out.push(items.slice(i, i + n));
  return out;
}

type Row = { verstr: string; status?: string | null };

/** One poll of the leaderboard, without re-fetching every page the user has
 *  scrolled through: the first page again, plus — by verstr — only the rows
 *  past it that can have changed (running ones and the *extraVerstrs* on
 *  screen). Everything else is kept as it was, and unchanged rows keep their
 *  identity. *fetchWhere* must apply the active filters too, so a re-asked
 *  row that no longer matches them drops out.
 *
 *  *hold* (the user scrolled down or selected rows) keeps every held row
 *  where it is, its cells updated (a re-asked one the filters no longer match
 *  drops out), and reports the news as `held` instead.
 *  The keyset cursor stays the held one (*getCursor*) while rows past the
 *  first page are kept. */
export async function refreshRows<R extends Row, P extends Page<R> = Page<R>>({
  getRows, fetchFirst, fetchWhere, extraVerstrs = [], hold = false, getCursor,
}: {
  /** The rows currently held — read after the requests, so a page appended
   *  meanwhile survives. */
  getRows: () => readonly R[] | undefined;
  /** Its other fields (a Jobs view search's counts) are kept. */
  fetchFirst: () => Promise<P>;
  fetchWhere: (query: string, limit: number) => Promise<{ rows: R[] }>;
  extraVerstrs?: readonly string[];
  hold?: boolean;
  getCursor?: () => string | null | undefined;
}): Promise<P & { held?: HeldChange }> {
  const first = await fetchFirst();
  const inFirst = new Set(first.rows.map((r) => r.verstr));
  const before = (getRows() ?? []).filter((r) => !inFirst.has(r.verstr));
  const extra = new Set(extraVerstrs);
  const asked = before
    .filter((r) => r.status === "running" || extra.has(r.verstr))
    .map((r) => r.verstr);

  const pages = await Promise.all(
    chunk(asked, VERSTR_CHUNK).map((ids) => fetchWhere(verstrInQuery(ids), ids.length)),
  );
  const fresh = new Map(pages.flatMap((p) => p.rows).map((r) => [r.verstr, r] as const));

  const current = getRows() ?? [];
  // Rows past the first page kept: the next page follows the held cursor.
  const heldCursor = getCursor && "next_cursor" in first ? { next_cursor: getCursor() } : {};
  const askedSet = new Set(asked);
  // Re-asked and not returned: the filters no longer match it.
  const matching = (r: R) => !askedSet.has(r.verstr) || fresh.has(r.verstr);
  if (hold && current.length) {
    for (const r of first.rows) fresh.set(r.verstr, r);
    const rows = current.filter(matching).map((r) => fresh.get(r.verstr) ?? r);
    const held = heldChange(current, first.rows);
    return { ...first, rows: stabilizeRows(current, rows), ...heldCursor, held };
  }
  const tail = current
    .filter((r) => !inFirst.has(r.verstr))
    .filter(matching)
    .map((r) => fresh.get(r.verstr) ?? r);
  return {
    ...first, rows: stabilizeRows(current, [...first.rows, ...tail]),
    ...(tail.length ? heldCursor : {}),
  };
}

function heldChange(current: readonly Row[], first: readonly Row[]): HeldChange | undefined {
  const have = new Set(current.map((r) => r.verstr));
  const onFirst = new Set(first.map((r) => r.verstr));
  const was = current.filter((r) => onFirst.has(r.verstr));
  const now = first.filter((r) => have.has(r.verstr));
  const added = first.length - now.length;
  const reordered = was.some((r, i) => r.verstr !== now[i].verstr);
  return added || reordered ? { added, reordered } : undefined;
}
