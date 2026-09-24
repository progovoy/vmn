import { stabilizeRows } from "../util/stableRows";

type Page<R> = { rows: R[]; total: number };

/** Verstrs per by-id request — keeps the query (and its URL) bounded. */
const VERSTR_CHUNK = 200;

/** The query language's membership test over verstrs. Verstrs never hold a
 *  quote, so plain double quotes are always a valid literal. */
export const verstrInQuery = (verstrs: readonly string[]) =>
  `verstr in (${verstrs.map((v) => `"${v}"`).join(", ")})`;

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
 *  row that no longer matches them drops out. */
export async function refreshRows<R extends Row>({
  getRows, fetchFirst, fetchWhere, extraVerstrs = [],
}: {
  /** The rows currently held — read after the requests, so a page appended
   *  meanwhile survives. */
  getRows: () => readonly R[] | undefined;
  fetchFirst: () => Promise<Page<R>>;
  fetchWhere: (query: string, limit: number) => Promise<{ rows: R[] }>;
  extraVerstrs?: readonly string[];
}): Promise<Page<R>> {
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
  const askedSet = new Set(asked);
  const tail = current
    .filter((r) => !inFirst.has(r.verstr))
    .filter((r) => !askedSet.has(r.verstr) || fresh.has(r.verstr))
    .map((r) => fresh.get(r.verstr) ?? r);
  return { rows: stabilizeRows(current, [...first.rows, ...tail]), total: first.total };
}
