/** The Jobs view's data (plan 23 W1): the top-level rows (`top=1`, or the
 *  jobs or single runs only, `top=jobs|singles`, §3.1), flat or
 *  grouped, kept fresh by the `top` scope's live events (polling while a
 *  run is in flight and the stream is down), plus the selection. */
import { useMemo, useState } from "react";
import { useFacets, useMetricsSchema } from "../../queries";
import { useBoardLive } from "../../hooks/useBoardLive";
import { useBoardRows } from "../../hooks/useBoardRows";
import { useBoardSelection } from "../../hooks/useBoardSelection";
import type { useLeaderboardView } from "../../hooks/useLeaderboardView";
import type { ExperimentRow } from "../../types";
import { metricGoal } from "../../util";
import { NO_GROUP } from "../../util/groupBy";
import { boardSort } from "../../util/groupCountSort";
import { boardRows } from "../../util/groupItems";
import { branchClause, combineQueries, searchClause } from "../../util/searchQuery";
import { hasSearch, type SearchFilter } from "../../util/searchScope";
import { IDX_SORT } from "../LeaderboardHead";
import { BIG_GROUP } from "../../util/groupClause";
import { bestOrder, mainMetric } from "./jobColumns";
import type { TopRuns } from "../../types";

type View = ReturnType<typeof useLeaderboardView>;

/** A job keeps the view live while any run of its tree runs. */
const treeRunning = (r: ExperimentRow) => r.status === "running" || r.tree_status === "running";

/** *top* null (not known yet) fetches nothing. */
export function useJobsBoard(ws: string, app: string, view: View, top: TopRuns | null) {
  const schema = useMetricsSchema(ws, app);
  const facets = useFacets(ws, app);
  const [paused, setPaused] = useState(false);
  // Parent run is no grouping of top-level runs: the URL's `group=parent` is this view.
  const chosen = view.groupParam && view.groupParam !== "parent" ? view.groupParam : NO_GROUP;
  const group = top === null ? null : chosen;

  const query = combineQueries(combineQueries(view.query, searchClause(view.search)), branchClause(view.branch));
  const sort = boardSort(view.sort, chosen);
  // A search covers every run (plan 23 W11): jobs are kept for their matching runs.
  const search = useMemo<SearchFilter>(() => ({
    query: view.query, search: view.search, branch: view.branch, archived: view.archived,
  }), [view.query, view.search, view.branch, view.archived]);
  const matchSubtree = hasSearch(search);
  const filter = useMemo(() => ({
    sort: sort ?? IDX_SORT,
    order: sort ? view.order : undefined,
    status: view.status || undefined,
    query: query || undefined,
    archived: view.archived || undefined,
    top: top ?? true,
    matchSubtree: matchSubtree || undefined,
  }), [sort, view.order, view.status, query, view.archived, top, matchSubtree]);

  const data = useBoardRows(ws, app, filter, {
    group, aggregateInUrl: view.aggParam, collapsed: view.collapsed, filterOver: BIG_GROUP,
  });
  const { refresh } = data;
  const rows = useMemo(() => (data.items ? boardRows(data.items) : []), [data.items]);
  const metric = mainMetric(rows, schema);
  const running = useBoardLive({
    ws, app, scope: "top", paused, rows, serverRunning: data.running > 0, refresh, isRunning: treeRunning,
  });

  const selection = useBoardSelection(ws, app, filter, rows, view, () => { refresh(); });
  const order = view.order ?? (sort ? bestOrder(sort, metric, schema) : "desc");

  return {
    data, rows, facets, group: chosen, selection, search: matchSubtree ? search : null,
    metric, goal: metric ? metricGoal(schema, metric) : null,
    sort: { sort: filter.sort, order, onSort: (s: string) => view.clickSort(s, bestOrder(s, metric, schema)) },
    live: { running, paused, setPaused },
    filtered: Boolean(filter.query || filter.status || filter.archived),
  };
}
