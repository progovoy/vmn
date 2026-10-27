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

/** A background refresher's health (experiments-status `refresher`,
 *  routes_shell.py); absent when the server refreshes inline. */
export interface RefresherHealth {
  alive: boolean; failing: boolean; failures: number;
  since_refresh_sec: number | null; refreshing_sec: number | null; last_error: string | null;
}

/** An index this far behind says so (a healthy one is ~1 s behind). */
const BEHIND_SEC = 300;

/** What an index that stopped keeping up says: `index 44 min behind`, or
 *  `index refresh failing` for a fresh failure; nothing while it loads (its
 *  progress says enough) or keeps up. */
export function staleText(status?: { indexing?: Indexing; refresher?: RefresherHealth }): string {
  const health = status?.refresher;
  if (!health || status?.indexing) return "";
  const behind = health.since_refresh_sec ?? health.refreshing_sec ?? 0;
  if (!health.failing && behind < BEHIND_SEC) return "";
  if (behind >= 60) return `index ${Math.floor(behind / 60)} min behind`;
  return health.failing ? "index refresh failing" : "";
}
