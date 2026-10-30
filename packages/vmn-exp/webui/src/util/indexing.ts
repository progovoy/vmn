/** What a store's index still loading says (experiments-status `indexing`,
 *  routes_shell.py): `indexing 12,000 / 45,386 runs`. */
import { fmtCount, plural } from "../util";

/** `total` is null while a cold index's store has not named its runs yet. */
export interface Indexing { loaded: number; total: number | null }

export function indexingText(indexing?: Indexing): string {
  if (!indexing) return "";
  const { loaded, total } = indexing;
  if (total === null) return loaded ? `indexing ${fmtCount(loaded)} runs…` : "indexing…";
  return `indexing ${fmtCount(loaded)} / ${fmtCount(total)} runs`;
}

/** An app tile's run count: the load's progress, else the status total, else
 *  the listed count (null on a store whose index holds none yet). */
export function appRunsText(status: { total: number; indexing?: Indexing } | undefined,
  listed: number | null): string {
  if (status?.indexing) return indexingText(status.indexing);
  const total = status?.total ?? listed;
  return total === null ? "counting runs…" : plural(total, "run");
}

/** A count of a store still indexing is of its runs so far: ` so far`. */
export const soFar = (status: { indexing?: Indexing }): string => (status.indexing ? " so far" : "");

/** Count parts (`13 stuck`) of a store still indexing, each marked so far. */
export function partsSoFar<T extends { text: string }>(parts: T[], status: { indexing?: Indexing }): T[] {
  const partial = soFar(status);
  return partial ? parts.map((p) => ({ ...p, text: p.text + partial })) : parts;
}

/** The run count a board counts against: the store's while it indexes (the
 *  snapshot holds only its newest runs), else the board's own. */
export const storeTotal = (boardTotal: number, indexing?: Indexing): number =>
  indexing?.total == null ? boardTotal : Math.max(boardTotal, indexing.total);
