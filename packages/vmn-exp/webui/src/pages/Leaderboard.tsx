import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { appName as toAppName } from "../api";
import { prefetchRun, useFacets, useMetricsSchema } from "../queries";
import { branchClause, combineQueries, searchClause } from "../util/searchQuery";
import { metricGoal, pollIntervalMs } from "../util";
import type { ExperimentRow } from "../types";
import { PageHead } from "../components/ui";
import NewExperiment from "../components/NewExperiment";
import LeaderboardFilter from "../components/LeaderboardFilter";
import { usePolling } from "../hooks/usePolling";
import { useLeaderboardRows } from "../hooks/useLeaderboardRows";
import { useLeaderboardView, type Order } from "../hooks/useLeaderboardView";
import { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import { useColumnPrefs } from "../hooks/useColumnPrefs";
import { useChartRows } from "../hooks/useChartRows";
import { useBoardSelection } from "../hooks/useBoardSelection";
import { collapsedByDefault, foldState, visibleRows } from "../util/sweepTree";
import LeaderboardCharts from "./LeaderboardCharts";
import LeaderboardTable, { IDX_SORT, TIMESTAMP_SORT, type ColumnEdits } from "./LeaderboardTable";
import { DATE_SORT_OF, moveColumn } from "./leaderboardColumns";
import LeaderboardToolbar from "./LeaderboardToolbar";

const NEWEST_FIRST = new Set([TIMESTAMP_SORT, IDX_SORT, ...Object.values(DATE_SORT_OF)]);

/** A column's best-first direction: newest first for time, else its goal's. */
const bestOrder = (schema: Parameters<typeof metricGoal>[0], col: string): Order =>
  !NEWEST_FIRST.has(col) && metricGoal(schema, col) === "min" ? "asc" : "desc";


/** One app's board: switching app starts from a clean slate (filters, brush,
 *  scroll), while the URL's own view params never remount it. */
export default function Leaderboard() {
  const { ws, app } = useParams() as { ws: string; app: string };
  return <AppLeaderboard key={`${ws}/${app}`} ws={ws} app={app} />;
}

function AppLeaderboard({ ws, app }: { ws: string; app: string }) {
  const appName = toAppName(app);
  const client = useQueryClient();
  const view = useLeaderboardView();
  const schema = useMetricsSchema(ws, app);
  const facets = useFacets(ws, app);
  const [live, setLive] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [brushed, setBrushed] = useState<Set<string> | null>(null);
  // Bumped when a saved view replaces the URL, so the filter bar re-reads it.
  const [filterGen, setFilterGen] = useState(0);

  // Search, branch and the typed query all travel to the server as one query.
  const serverQuery = combineQueries(
    combineQueries(view.query, searchClause(view.search)), branchClause(view.branch),
  );
  const filter = useMemo(() => ({
    sort: view.sort ?? IDX_SORT,
    order: view.sort ? view.order : undefined,
    status: view.status || undefined,
    query: serverQuery || undefined,
    archived: view.archived || undefined,
  }), [view.sort, view.order, view.status, serverQuery, view.archived]);
  const data = useLeaderboardRows(ws, app, filter);
  const rows = data.rows;

  // Keep refreshing on our own while a run is still in flight, at the cadence
  // its heartbeat can actually move the status at.
  const { anyRunning, heartbeatSec } = useMemo(() => {
    let running = false;
    let fastest: number | null = null;
    for (const r of rows ?? []) {
      if (r.status === "running") running = true;
      const hb = r.heartbeat_interval_sec;
      if (typeof hb === "number" && (fastest === null || hb < fastest)) fastest = hb;
    }
    return { anyRunning: running, heartbeatSec: fastest };
  }, [rows]);
  usePolling(data.refresh, pollIntervalMs(heartbeatSec), live || anyRunning);

  const base = `/ws/${ws}/app/${app}`;
  const colPrefs = useColumnPrefs(`${ws}/${app}`);
  const [tableWidth, setTableWidth] = useState(0);
  const cols = useLeaderboardColumns(rows, schema, view.hidden, base, facets, view.colOrder, view.pinned, colPrefs, tableWidth);
  const { setWidth, setOrder } = colPrefs;
  const ids = cols.layout.ids;
  const columnEdits = useMemo<ColumnEdits>(() => ({
    onResize: setWidth,
    onMove: (from, to) => {
      const next = moveColumn(ids ?? [], from, to);
      if (next !== ids) setOrder(next);
    },
  }), [setWidth, setOrder, ids]);

  const all = useMemo(() => rows ?? [], [rows]);
  const chart = useChartRows(
    ws, app, filter, view.chart, cols.metricCols, cols.paramCols, all, data.total,
  );
  // A brush in the parallel view narrows the table; the chart keeps every row
  // so its brush indices stay meaningful.
  const onBrush = useCallback(
    (indices: number[] | null) => setBrushed(indices
      ? new Set(indices.map((i) => chart.rows[i]?.verstr).filter((v): v is string => !!v))
      : null),
    [chart.rows],
  );
  const { expanded, collapsed } = view;
  const tableRows = useMemo(() => {
    if (!rows) return rows;
    const topLevel = rows.filter((r) => !r.depth);
    const brushedRows = brushed && view.chart === "parallel" ? topLevel.filter((r) => brushed.has(r.verstr)) : topLevel;
    return visibleRows(brushedRows, expanded, collapsed);
  }, [rows, brushed, view.chart, expanded, collapsed]);
  const collapsedOf = useCallback(
    (r: ExperimentRow) => foldState(r, expanded, collapsed),
    [expanded, collapsed],
  );
  const { toggleCollapsed } = view;
  const onFold = useCallback((r: ExperimentRow) => toggleCollapsed(r.verstr, collapsedByDefault(r)), [toggleCollapsed]);
  const selection = useBoardSelection(ws, app, filter, tableRows ?? [], view, () => { data.refresh(); });

  const onPrefetch = useCallback(
    (verstr: string) => { prefetchRun(client, ws, app, verstr); },
    [client, ws, app],
  );
  const sortState = {
    sort: view.sort,
    reversed: Boolean(view.sort && view.order && view.order !== bestOrder(schema, view.sort)),
    onSort: (col: string) => view.clickSort(col, bestOrder(schema, col)),
  };

  const onCreated = () => {
    const known = new Set(all.map((r) => r.verstr));
    view.openCreate(false);
    // The same request as any refresh: the active sort and filters still apply.
    data.refresh().then((next) => {
      if (next) setFlash(next.rows.find((r: ExperimentRow) => !known.has(r.verstr))?.verstr ?? null);
    });
  };

  if (data.pageError) return <div className="error">{data.pageError}</div>;

  const filtered = view.query || view.status || view.search || view.branch || view.archived;
  const empty = rows !== undefined && rows.length === 0 && !filtered;
  const sortLabel = view.sort ?? cols.primary;

  return (
    <>
      <PageHead title={appName} what="experiment leaderboard" />
      <p className="page-sub">
        {rows === undefined ? "loading runs…"
          : tableRows!.length !== data.total ? `${tableRows!.length} of ${data.total} runs`
          : `${data.total} runs`}
        {sortLabel && (
          <>
            {" · sorted by "}<b>{sortLabel}</b>
            {" · "}{sortState.reversed ? "worst first" : "best first"}
          </>
        )}
      </p>

      {view.creating && (
        <NewExperiment
          ws={ws} app={app} appName={appName}
          onClose={() => view.openCreate(false)}
          onCreated={onCreated}
        />
      )}

      {/* Filtered down to nothing is not "no experiments yet": keep the table
          and its filter bar, or there is no way back from the query. */}
      {empty ? (
        !view.creating && (
          <div className="empty">
            No experiments yet. Capture your working state:
            <div className="cli-hint" style={{ margin: "12px auto", maxWidth: 420 }}>
              vmn-exp create {appName}
            </div>
            <button className="primary" onClick={() => view.openCreate(true)}>+ New experiment</button>
          </div>
        )
      ) : (
        <>
          <LeaderboardToolbar
            ws={ws} app={app} base={base} view={view} cols={cols} selection={selection}
            total={data.total} live={live} onLive={() => setLive((v) => !v)}
            onViewApplied={() => setFilterGen((g) => g + 1)}
            onResetColumns={colPrefs.customized ? colPrefs.reset : undefined}
          />

          <LeaderboardFilter
            key={filterGen}
            rows={facets ? undefined : all}
            branches={facets?.branches ?? null}
            facets={cols.suggestFacets}
            initial={{ search: view.search, branch: view.branch, status: view.status, query: view.query }}
            onStatusChange={view.setStatus}
            onQueryChange={view.setQuery}
            onSearchChange={view.setSearch}
            onBranchChange={view.setBranch}
            queryError={data.queryError}
            archived={view.archived}
            onArchivedChange={view.setArchived}
          />

          <LeaderboardCharts
            view={view.chart} onView={view.setChart} rows={chart.rows} label={chart.label}
            metricCols={cols.metricCols} paramCols={cols.paramCols} schema={schema} onBrush={onBrush}
            importance={{ ws, app, filter, defaultMetric: sortLabel }}
          />

          <LeaderboardTable
            rows={tableRows}
            layout={cols.layout}
            sort={sortState}
            selected={view.selected}
            flash={flash}
            onToggle={selection.toggle}
            onPrefetch={onPrefetch}
            collapsedOf={collapsedOf}
            onFold={onFold}
            hasMore={all.length < data.total}
            onNearEnd={data.loadMore}
            visibleRef={data.visibleRef}
            edits={columnEdits}
            onFit={setTableWidth}
          />
          {rows !== undefined && all.length < data.total && (
            <div className="load-more">
              <button onClick={data.loadMore}>Load more ({data.total - all.length} remaining)</button>
              {data.moreError && <span className="error">{data.moreError}</span>}
            </div>
          )}
          <div className="cli-card">
            vmn-exp list {appName}{sortLabel ? ` --sort ${sortLabel}` : ""}
          </div>
        </>
      )}
    </>
  );
}
