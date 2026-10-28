/** Instant view switching: once the experiments page has shown its view a
 *  moment, the other top views' first pages (Outer runs, Single runs, All
 *  runs, or Runs for an app without outer runs) are fetched into the cache
 *  under the same filters, with the exact keys their boards ask with. Each
 *  is an index read (milliseconds on the server); nothing per run. */
import { useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { boardFilter } from "../../hooks/useBoardFilter";
import { prefetchRows } from "../../hooks/useLeaderboardRows";
import type { useLeaderboardView } from "../../hooks/useLeaderboardView";
import type { RowsFilter } from "../../queries";
import { NO_GROUP } from "../../util/groupBy";
import { hasSearch } from "../../util/searchScope";
import type { JobsKindState } from "./jobsKind";
import type { Preset } from "./presets";

/** How long the shown view has the network to itself first. */
export const PREFETCH_DELAY_MS = 1_000;

type View = ReturnType<typeof useLeaderboardView>;
export type TopView = "jobs" | "singles" | "top" | "all";

/** Each top view's first-page filter as its board builds it after a switch:
 *  the filters stay, the sort/order/grouping are dropped (BOARD_ONLY_PARAMS). */
export function viewFilters(view: View, withJobs: boolean): Partial<Record<TopView, RowsFilter>> {
  const v = { ...view, sort: null, order: undefined };
  const matchSubtree = hasSearch(view) || undefined;
  const all = boardFilter(v, NO_GROUP, { scope: undefined, top: undefined });
  if (!withJobs) return { top: boardFilter(v, NO_GROUP, { top: true, matchSubtree }), all };
  return {
    jobs: boardFilter(v, NO_GROUP, { top: "jobs" as const, matchSubtree }),
    singles: boardFilter(v, NO_GROUP, { scope: undefined, top: "singles" as const }),
    all,
  };
}

/** *shown* is the view on screen (never prefetched; a preset, plan 28
 *  §4.5, is none of them); *kind* null facets (not known yet) wait. */
export function useViewPrefetch(ws: string, app: string, view: View, shown: TopView | Preset, kind: JobsKindState) {
  const client = useQueryClient();
  const known = kind.counts !== null;
  const withJobs = kind.kind !== null;
  const filters = useMemo(
    () => (known ? viewFilters(view, withJobs) : {}),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [known, withJobs, view.status, view.query, view.search, view.branch, view.archived],
  );
  const hash = JSON.stringify(filters);
  useEffect(() => {
    const others = Object.entries(filters).filter(([id]) => id !== shown) as [TopView, RowsFilter][];
    if (!others.length) return;
    const timer = setTimeout(() => {
      for (const [, f] of others) void prefetchRows(client, ws, app, f).catch(() => {});
    }, PREFETCH_DELAY_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, ws, app, shown, hash]);
}
