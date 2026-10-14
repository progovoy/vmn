/** A board of runs (plan 22's table), shared by the All runs view and a
 *  job's Runs tab (plan 23 W3): the URL's filters as one server filter, the
 *  rows (flat or grouped), their freshness, columns, selection and group
 *  actions. *scope* (a job's verstr) narrows every request to its subtree. */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { prefetchRun, useFacets, useMetricsSchema } from "../queries";
import type { ExperimentRow } from "../types";
import { boardRows } from "../util/groupItems";
import { NO_GROUP } from "../util/groupBy";
import { runContextSearch } from "../util/runContext";
import { queryHelpData } from "../util/queryHelp";
import { boardSortState } from "../pages/boardSortState";
import { useBoardAggregate } from "./useBoardAggregate";
import { useBoardFilter } from "./useBoardFilter";
import { useBoardGroupActions } from "./useBoardGroupActions";
import { useBoardGrouping } from "./useBoardGrouping";
import { useBoardLive } from "./useBoardLive";
import { useBoardRows } from "./useBoardRows";
import { useBoardSelection } from "./useBoardSelection";
import { useColumnEdits } from "./useColumnEdits";
import { useColumnPrefs } from "./useColumnPrefs";
import { useLeaderboardColumns } from "./useLeaderboardColumns";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = ReturnType<typeof useLeaderboardView>;

export interface RunsBoardOptions {
  paused: boolean;
  /** A job's verstr: the board is its subtree. */
  scope?: string;
  /** The job's name, naming its selected queries in the tray. */
  scopeLabel?: string;
  /** Picking "parent run" calls it instead (the Jobs view, §3.4). */
  onParent?: () => void;
  /** Narrows the rows on screen (a chart brush). */
  keep?: (r: ExperimentRow) => boolean;
  /** A group of more runs than this opens as a filter (§3.4) through *onOpenGroup*. */
  openGroup?: { over: number; onOpen: (clause: string) => void };
  /** Also told of each live change. */
  onLive?: () => unknown;
}

export function useRunsBoard(ws: string, app: string, view: View, opts: RunsBoardOptions) {
  const { scope, keep, paused } = opts;
  const client = useQueryClient();
  const schema = useMetricsSchema(ws, app);
  const facets = useFacets(ws, app, scope ? { scope } : undefined);
  const groupBy = useBoardGrouping(ws, app, view, opts.onParent, scope);

  const { sort, serverQuery, filter, filtered } = useBoardFilter(view, groupBy.group, { scope });
  // Every run is a row (plan 22 G1); grouped, under its group's header row.
  const data = useBoardRows(ws, app, filter, {
    group: groupBy.group, aggregateInUrl: groupBy.aggregateInUrl, collapsed: view.collapsed, keep,
    filterOver: opts.openGroup?.over,
  });
  const grouping = useBoardAggregate(groupBy, view, data);
  const rows = data.rows;
  const all = useMemo(() => rows ?? [], [rows]);
  const { refresh } = data;
  const anyRunning = useBoardLive({
    ws, app, scope, paused, rows, serverRunning: data.running > 0, refresh, onChange: opts.onLive,
  });

  const base = `/ws/${ws}/app/${app}`;
  const colPrefs = useColumnPrefs(`${ws}/${app}`);
  const [tableWidth, setTableWidth] = useState(0);
  const cols = useLeaderboardColumns(
    rows, schema, view.hidden, base, facets, view.colOrder, view.pinned, colPrefs, tableWidth, view.shown,
  );
  const columnEdits = useColumnEdits(view, cols, colPrefs);
  // A flat job board's run links carry its order and their place in it (W7).
  const flatJob = scope && groupBy.group === NO_GROUP;
  const layout = useMemo(() => (flatJob ? {
    ...cols.layout,
    runSearch: (i: number) => runContextSearch({
      scope, q: filter.query, status: filter.status, sort: filter.sort, order: filter.order,
    }, i),
  } : cols.layout), [flatJob, cols.layout, scope, filter]);
  const queryHelp = useMemo(() => queryHelpData({
    facets: cols.suggestFacets, branches: facets?.branches ?? [], rows: all, schema,
    primary: sort ?? cols.primary ?? cols.visibleMetrics[0],
  }), [cols.suggestFacets, facets, all, schema, sort, cols.primary, cols.visibleMetrics]);

  const tableItems = data.items;
  const tableRows = useMemo(() => tableItems && boardRows(tableItems), [tableItems]);
  // A job's selection may be its whole query (plan 23 S4) rather than verstrs.
  const { scopeLabel } = opts;
  const byQuery = useMemo(
    () => (scope ? { scope, q: serverQuery, status: view.status, label: scopeLabel } : undefined),
    [scope, serverQuery, view.status, scopeLabel],
  );
  const selection = useBoardSelection(ws, app, filter, tableRows ?? [], view, byQuery);
  const { groupActions, chartGrouping } = useBoardGroupActions(
    data, grouping, view.toggleCollapsed, selection, opts.openGroup?.onOpen,
  );

  const onPrefetch = useCallback(
    (verstr: string) => { prefetchRun(client, ws, app, verstr); },
    [client, ws, app],
  );
  const sortState = boardSortState(sort, view.order, schema, view.clickSort);

  return {
    schema, facets, sort, filter, serverQuery, data, grouping, rows, all, refresh, anyRunning,
    base, colPrefs, setTableWidth, cols, layout, columnEdits, queryHelp, filtered,
    tableItems, tableRows, selection, groupActions, chartGrouping, onPrefetch, sortState,
    sortLabel: sort ?? cols.primary,
  };
}

export type RunsBoard = ReturnType<typeof useRunsBoard>;
