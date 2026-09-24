import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { appName as toAppName } from "../api";
import { useAppQueryClient } from "../queryClient";
import { prefetchRun, useFacets, useMetricsSchema } from "../queries";
import { branchClause, combineQueries, searchClause } from "../util/searchQuery";
import { metricGoal, pollIntervalMs } from "../util";
import type { ExperimentRow } from "../types";
import { PageHead } from "../components/ui";
import NewExperiment from "../components/NewExperiment";
import LeaderboardFilter from "../components/LeaderboardFilter";
import ColumnPicker from "../components/ColumnPicker";
import LiveToggle from "../components/LiveToggle";
import { usePolling } from "../hooks/usePolling";
import { useLeaderboardRows } from "../hooks/useLeaderboardRows";
import { useLeaderboardView, type Order } from "../hooks/useLeaderboardView";
import { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import { useChartRows } from "../hooks/useChartRows";
import LeaderboardCharts from "./LeaderboardCharts";
import LeaderboardTable, { TIMESTAMP_SORT } from "./LeaderboardTable";

/** A column's best-first direction: newest first for time, else its goal's. */
const bestOrder = (schema: Parameters<typeof metricGoal>[0], col: string): Order =>
  col !== TIMESTAMP_SORT && metricGoal(schema, col) === "min" ? "asc" : "desc";


/** One app's board: switching app starts from a clean slate (filters, brush,
 *  scroll), while the URL's own view params never remount it. */
export default function Leaderboard() {
  const { ws, app } = useParams() as { ws: string; app: string };
  return <AppLeaderboard key={`${ws}/${app}`} ws={ws} app={app} />;
}

function AppLeaderboard({ ws, app }: { ws: string; app: string }) {
  const appName = toAppName(app);
  const navigate = useNavigate();
  const client = useAppQueryClient();
  const view = useLeaderboardView();
  const schema = useMetricsSchema(ws, app);
  const facets = useFacets(ws, app);
  const [live, setLive] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [brushed, setBrushed] = useState<Set<string> | null>(null);

  // Search, branch and the typed query all travel to the server as one query.
  const serverQuery = combineQueries(
    combineQueries(view.query, searchClause(view.search)), branchClause(view.branch),
  );
  const filter = useMemo(() => ({
    sort: view.sort ?? undefined,
    order: view.sort ? view.order : undefined,
    status: view.status || undefined,
    query: serverQuery || undefined,
  }), [view.sort, view.order, view.status, serverQuery]);
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
  const cols = useLeaderboardColumns(rows, schema, view.hidden, base, facets);

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
  const tableRows = useMemo(
    () => (rows && brushed && view.chart === "parallel" ? rows.filter((r) => brushed.has(r.verstr)) : rows),
    [rows, brushed, view.chart],
  );

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

  const filtered = view.query || view.status || view.search || view.branch;
  const empty = rows !== undefined && rows.length === 0 && !filtered;
  const sortLabel = view.sort ?? cols.primary;
  const selected = [...view.selected];

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
              vmn exp create {appName}
            </div>
            <button className="primary" onClick={() => view.openCreate(true)}>+ New experiment</button>
          </div>
        )
      ) : (
        <>
          <div className="toolbar">
            <span className="legend-chip"><span className="sq" /> best in column</span>
            <LiveToggle live={live} onToggle={() => setLive((v) => !v)} />
            <span className="spacer" />
            {selected.length === 2 && (
              <button className="primary" onClick={() => navigate(
                `${base}/compare?v=${encodeURIComponent(selected[0])}&to=${encodeURIComponent(selected[1])}`,
              )}>
                Compare 2 selected →
              </button>
            )}
            {selected.length >= 2 && (
              <button className="primary" onClick={() => navigate(
                `${base}/overlay?runs=${selected.map(encodeURIComponent).join(",")}`,
              )}>
                Overlay curves →
              </button>
            )}
            {!view.creating && <button onClick={() => view.openCreate(true)}>+ New experiment</button>}
            <ColumnPicker
              columns={cols.paramCols} visible={cols.visibleParams}
              onToggle={(c) => view.toggleHidden(`p:${c}`)}
              metricColumns={cols.metricCols} visibleMetrics={cols.visibleMetrics}
              onToggleMetric={(c) => view.toggleHidden(`m:${c}`)}
            />
          </div>

          <LeaderboardFilter
            rows={facets ? undefined : all}
            branches={facets?.branches ?? null}
            facets={cols.suggestFacets}
            initial={{ search: view.search, branch: view.branch, status: view.status, query: view.query }}
            onStatusChange={view.setStatus}
            onQueryChange={view.setQuery}
            onSearchChange={view.setSearch}
            onBranchChange={view.setBranch}
            queryError={data.queryError}
          />

          <LeaderboardCharts
            view={view.chart} onView={view.setChart} rows={chart.rows} label={chart.label}
            metricCols={cols.metricCols} paramCols={cols.paramCols} schema={schema} onBrush={onBrush}
          />

          <LeaderboardTable
            rows={tableRows}
            layout={cols.layout}
            sort={sortState}
            selected={view.selected}
            flash={flash}
            onToggle={view.toggleSelected}
            onPrefetch={onPrefetch}
            hasMore={all.length < data.total}
            onNearEnd={data.loadMore}
            visibleRef={data.visibleRef}
          />
          {rows !== undefined && all.length < data.total && (
            <div className="load-more">
              <button onClick={data.loadMore}>Load more ({data.total - all.length} remaining)</button>
              {data.moreError && <span className="error">{data.moreError}</span>}
            </div>
          )}
          <div className="cli-card">
            vmn exp list {appName}{sortLabel ? ` --sort ${sortLabel}` : ""}
          </div>
        </>
      )}
    </>
  );
}
