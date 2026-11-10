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
import { NO_GROUP } from "../../util/groupBy";
import { boardRows } from "../../util/groupItems";
import { hasSearch, type SearchFilter } from "../../util/searchScope";
import { combineQueries } from "../../util/searchQuery";
import { BIG_GROUP } from "../../util/groupClause";
import { boardSortState } from "../boardSortState";
import { jobValueOrder } from "./jobColumns";
import type { MetricsSchema, TopRuns } from "../../types";
import { metricGoal, type Goal } from "../../util";
import { PRESETS, type Preset } from "./presets";
import { treeStatusQuery } from "./treeStatus";

type View = ReturnType<typeof useLeaderboardView>;

/** A job keeps the view live while any run of its tree runs. */
const treeRunning = (r: ExperimentRow) => r.status === "running" || r.tree_status === "running";

/** The goal `job:value` sorts toward without a `rolled`: the server orders
 *  it by the aggregate's metric, so only the URL's `job_agg_metric`'s goal in
 *  the schema; undefined while that is not known (plan 32: no guessed goal). */
function valueGoalBeforeRolled(schema: MetricsSchema | null, metric: string | null): Goal | undefined {
  return metric && schema?.[metric] ? metricGoal(schema, metric) : undefined;
}

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
  const tree = top === "jobs" ? treeStatusQuery(view.status, view.failedPct, view.lost) : "";
  const topQuery = combineQueries(fixed?.query ?? "", tree || null) || undefined;
  // One row per group (plan 34 §1): the server sends the headers alone.
  const collapseAll = chosen !== NO_GROUP && view.collapseAll;
  const { filter, filtered } = useBoardFilter(view, chosen, {
    top: top ?? true, matchSubtree: matchSubtree || undefined, topQuery,
    status: tree ? undefined : view.status || undefined,
    jobAgg: view.jobAgg.agg ?? undefined, jobAggBy: view.jobAgg.by ?? undefined,
    jobAggValue: view.jobAgg.value ?? undefined, jobAggMetric: view.jobAgg.metric ?? undefined,
    collapseAll: collapseAll || undefined,
  });

  const data = useBoardRows(ws, app, filter, {
    group, aggregateInUrl: view.aggParam, collapsed: view.collapsed, filterOver: BIG_GROUP,
  });
  const { refresh } = data;
  const rows = useMemo(() => (data.items ? boardRows(data.items) : []), [data.items]);
  // The server's main metric, never one picked from the rows (plan 32 F10).
  const metric = data.main?.metric ?? null;
  const goal = data.main?.goal ?? null;
  // The answered aggregate (plan 31 §2): one per board, so any row's names
  // it; with one row per group, any header's (plan 34 §1).
  const rolled = useMemo(() => rows.find((r) => r.job?.rolled)?.job?.rolled
    ?? data.groups?.flatMap((g) => Object.values(g.job_aggregates ?? {}))[0] ?? null, [rows, data.groups]);
  // The groups' aggregate (`agg=`, else the server's answer): the toolbar's and the headers'.
  const aggregate = view.aggParam ?? data.aggregate ?? data.defaultAggregate ?? "mean";
  const running = useBoardLive({
    ws, app, scope: "top", paused, rows, serverRunning: data.running > 0, refresh, isRunning: treeRunning,
  });

  const selection = useBoardSelection(ws, app, filter, rows, view);
  const valueGoal = rolled ? rolled.goal : valueGoalBeforeRolled(schema, view.jobAgg.metric);
  const sort = boardSortState(filter.sort, view.order, schema, view.clickSort, (s) => jobValueOrder(s, valueGoal));

  return {
    data, rows, facets, group: chosen, selection, search: matchSubtree ? search : null,
    metric, goal, rolled, aggregate, collapseAll,
    sort: { sort: filter.sort, order: sort.order, onSort: sort.onSort },
    live: { running, paused, setPaused },
    filtered: filtered || Boolean(fixed), topQuery,
  };
}
