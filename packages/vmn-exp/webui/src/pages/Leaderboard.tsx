import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { appName as toAppName } from "../api";
import ReportsUsing from "../components/ReportsUsing";
import { prefetchRun, useFacets, useMetricsSchema } from "../queries";
import { branchClause, combineQueries, searchClause, statusClause } from "../util/searchQuery";
import { metricGoal, pollIntervalMs } from "../util";
import type { ExperimentRow } from "../types";
import { PageHead } from "../components/ui";
import NewExperiment from "../components/NewExperiment";
import LeaderboardFilter from "../components/LeaderboardFilter";
import SimilarSearch from "../components/SimilarSearch";
import { usePolling } from "../hooks/usePolling";
import { useLeaderboardRows } from "../hooks/useLeaderboardRows";
import { useLeaderboardView, type Order } from "../hooks/useLeaderboardView";
import { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import { useColumnPrefs } from "../hooks/useColumnPrefs";
import { useBoardSelection } from "../hooks/useBoardSelection";
import { collapsedByDefault, foldState, visibleRows } from "../util/sweepTree";
import BoardTabs, { BOARD_PANEL_ID, boardTabId } from "./BoardTabs";
import LeaderboardChartsPanel from "./LeaderboardChartsPanel";
import LeaderboardSelectionBar from "./LeaderboardSelectionBar";
import LeaderboardTable, { IDX_SORT, TIMESTAMP_SORT, type ColumnEdits } from "./LeaderboardTable";
import { DATE_SORT_OF, moveColumn } from "./leaderboardColumns";
import LeaderboardToolbar from "./LeaderboardToolbar";
import { useCanCreateRun } from "../shell/useAppExists";

const NEWEST_FIRST = new Set([TIMESTAMP_SORT, IDX_SORT, ...Object.values(DATE_SORT_OF)]);

/** A column's best-first direction: newest first for time, else its goal's. */
const bestOrder = (schema: Parameters<typeof metricGoal>[0], col: string): Order =>
  !NEWEST_FIRST.has(col) && metricGoal(schema, col) === "min" ? "asc" : "desc";

/** An existing app without runs: the CLI line, plus a New run button where a
 *  run can be created here (a known app, a writable git workspace). */
function EmptyBoard({ ws, app, appName, onCreate }: {
  ws: string; app: string; appName: string; onCreate: () => void;
}) {
  const canCreate = useCanCreateRun(ws, app);
  return (
    <div className="empty">
      No runs yet in {appName}. Capture your working state:
      <div className="cli-hint" style={{ margin: "12px auto", maxWidth: 420 }}>
        vmn-exp create {appName}
      </div>
      {canCreate && <button className="primary" onClick={onCreate}>New run</button>}
    </div>
  );
}

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
  // The search box's "similar" mode text; null shows the table.
  const [similarText, setSimilarText] = useState<string | null>(null);

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
  // The similar mode keeps the bar's other filters: the box holds its text.
  const similarQuery = combineQueries(
    combineQueries(view.query, branchClause(view.branch)), statusClause(view.status),
  );
  const similarFilter = useMemo(() => ({
    query: similarQuery || undefined,
    archived: view.archived || undefined,
  }), [similarQuery, view.archived]);
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
  const cols = useLeaderboardColumns(
    rows, schema, view.hidden, base, facets, view.colOrder, view.pinned, colPrefs, tableWidth, view.shown,
  );
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
  const charting = view.tab === "charts";
  // A brush in the parallel view (Charts tab) narrows the table.
  const brush = charting && view.chart === "parallel" ? brushed : null;
  const { expanded, collapsed } = view;
  const tableRows = useMemo(() => {
    if (!rows) return rows;
    const topLevel = rows.filter((r) => !r.depth);
    const brushedRows = brush ? topLevel.filter((r) => brush.has(r.verstr)) : topLevel;
    return visibleRows(brushedRows, expanded, collapsed);
  }, [rows, brush, expanded, collapsed]);
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

      {/* Filtered down to nothing is not "no runs yet": keep the table
          and its filter bar, or there is no way back from the query. */}
      {empty ? (
        !view.creating && (
          <EmptyBoard ws={ws} app={app} appName={appName} onCreate={() => view.openCreate(true)} />
        )
      ) : (
        <>
          <LeaderboardToolbar
            ws={ws} app={app} view={view} cols={cols}
            live={live} onLive={() => setLive((v) => !v)}
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
            onSimilarChange={setSimilarText}
          />

          {similarText !== null ? (
            <SimilarSearch ws={ws} app={app} text={similarText} filter={similarFilter} />
          ) : (
            <>
              <BoardTabs tab={view.tab} onTab={view.setTab} />
              <div role="tabpanel" id={BOARD_PANEL_ID} aria-labelledby={boardTabId(view.tab)}>
                {charting && (
                  <LeaderboardChartsPanel
                    ws={ws} app={app} filter={filter} view={view.chart} onView={view.setChart}
                    loaded={all} total={data.total} metricCols={cols.metricCols} paramCols={cols.paramCols}
                    allParams={cols.suggestFacets.param_keys} schema={schema} defaultMetric={sortLabel}
                    onBrushed={setBrushed}
                  />
                )}

                <LeaderboardTable
                  rows={tableRows}
                  layout={cols.layout}
                  sort={sortState}
                  selected={view.selected}
                  flash={flash}
                  onToggle={selection.toggle}
                  headerCheck={{ state: selection.headerCheck, onToggle: selection.toggleAll }}
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
              </div>
            </>
          )}
          <ReportsUsing ws={ws} app={appName} />
          <div className="cli-card">
            vmn-exp list {appName}{sortLabel ? ` --sort ${sortLabel}` : ""}
          </div>
          <LeaderboardSelectionBar
            selected={[...view.selected]}
            total={data.total}
            base={base}
            showUnarchive={view.archived}
            archiving={selection.archiving}
            archiveError={selection.archiveError}
            onClear={() => view.setSelected([])}
            onSelectAll={selection.selectAll}
            onArchive={selection.archive}
          />
        </>
      )}
    </>
  );
}
