/** The Jobs view's data (plan 23 W1): the top-level rows (`top=1`, or the
 *  jobs or single runs only, `top=jobs|singles`, §3.1), flat or
 *  grouped, kept fresh by the `top` scope's live events (polling while a
 *  run is in flight and the stream is down), plus the selection. A
 *  *preset* (Live, Review) adds its query on the top rows and its sort. */
import { useMemo, useState } from "react";
import { useFacets, useMetricsSchema } from "../../queries";
import { useBoardFilter } from "../../hooks/useBoardFilter";
import { useBoardLive } from "../../hooks/useBoardLive";
import { useBoardRows } from "../../hooks/useBoardRows";
import { useBoardSelection } from "../../hooks/useBoardSelection";
import type { useLeaderboardView } from "../../hooks/useLeaderboardView";
import type { ExperimentRow } from "../../types";
import { metricGoal } from "../../util";
import { NO_GROUP } from "../../util/groupBy";
import { boardRows } from "../../util/groupItems";
import { hasSearch, type SearchFilter } from "../../util/searchScope";
import { combineQueries } from "../../util/searchQuery";
import { BIG_GROUP } from "../../util/groupClause";
import { boardSortState } from "../boardSortState";
import { jobBestOrder, mainMetric } from "./jobColumns";
import type { TopRuns } from "../../types";
import { PRESETS, type Preset } from "./presets";
import { treeStatusQuery } from "./treeStatus";

type View = ReturnType<typeof useLeaderboardView>;

/** A job keeps the view live while any run of its tree runs. */
const treeRunning = (r: ExperimentRow) => r.status === "running" || r.tree_status === "running";

/** *top* null (not known yet) fetches nothing. */
export function useJobsBoard(ws: string, app: string, shown: View, top: TopRuns | null, preset?: Preset) {
  const fixed = preset && PRESETS[preset];
  const view = fixed && !shown.sort ? { ...shown, sort: fixed.sort } : shown;
  const schema = useMetricsSchema(ws, app);
  const facets = useFacets(ws, app);
  const [paused, setPaused] = useState(false);
  // Parent run is no grouping of top-level runs: the URL's `group=parent` is this view.
  const chosen = view.groupParam && view.groupParam !== "parent" ? view.groupParam : NO_GROUP;
  const group = top === null ? null : chosen;

  // A search covers every run (plan 23 W11): jobs are kept for their matching runs.
  const search = useMemo<SearchFilter>(() => ({
    query: view.query, search: view.search, branch: view.branch, archived: view.archived,
  }), [view.query, view.search, view.branch, view.archived]);
  const matchSubtree = hasSearch(search);
  // The outer runs match a status by their trees, beside the preset's query.
  const tree = top === "jobs" ? treeStatusQuery(view.status) : "";
  const topQuery = combineQueries(fixed?.query ?? "", tree || null) || undefined;
  const { filter, filtered } = useBoardFilter(view, chosen, {
    top: top ?? true, matchSubtree: matchSubtree || undefined, topQuery,
    status: tree ? undefined : view.status || undefined,
  });

  const data = useBoardRows(ws, app, filter, {
    group, aggregateInUrl: view.aggParam, collapsed: view.collapsed, filterOver: BIG_GROUP,
  });
  const { refresh } = data;
  const rows = useMemo(() => (data.items ? boardRows(data.items) : []), [data.items]);
  const metric = mainMetric(rows, schema);
  const running = useBoardLive({
    ws, app, scope: "top", paused, rows, serverRunning: data.running > 0, refresh, isRunning: treeRunning,
  });

  const selection = useBoardSelection(ws, app, filter, rows, view);
  const sort = boardSortState(filter.sort, view.order, schema, view.clickSort, (s) => jobBestOrder(s, metric, schema));

  return {
    data, rows, facets, group: chosen, selection, search: matchSubtree ? search : null,
    metric, goal: metric ? metricGoal(schema, metric) : null,
    sort: { sort: filter.sort, order: sort.order ?? "desc", onSort: sort.onSort },
    live: { running, paused, setPaused },
    filtered: filtered || Boolean(fixed), topQuery,
  };
}
