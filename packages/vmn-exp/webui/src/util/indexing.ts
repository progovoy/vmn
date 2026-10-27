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
