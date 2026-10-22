/** What a store's index still loading says (experiments-status `indexing`,
 *  routes_shell.py): `indexing 12,000 / 45,386 runs`. */
import { fmtCount, plural } from "../util";

export interface Indexing { loaded: number; total: number }

export const indexingText = (indexing?: Indexing) =>
  indexing ? `indexing ${fmtCount(indexing.loaded)} / ${fmtCount(indexing.total)} runs` : "";

/** An app tile's run count: the load's progress, else the status total, else
 *  the listed count (null on a store whose index holds none yet). */
export function appRunsText(status: { total: number; indexing?: Indexing } | undefined,
  listed: number | null): string {
  if (status?.indexing) return indexingText(status.indexing);
  const total = status?.total ?? listed;
  return total === null ? "counting runs…" : plural(total, "run");
}
