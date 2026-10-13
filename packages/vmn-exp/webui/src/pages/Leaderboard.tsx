import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { appName as toAppName } from "../api";
import ReportsUsing from "../components/ReportsUsing";
import { prefetchRun, useFacets, useMetricsSchema } from "../queries";
import { branchClause, combineQueries, searchClause, statusClause } from "../util/searchQuery";
import { metricGoal, pollIntervalMs } from "../util";
import type { ExperimentRow } from "../types";
import NewExperiment from "../components/NewExperiment";
import LeaderboardFilter from "../components/LeaderboardFilter";
import SimilarSearch from "../components/SimilarSearch";
import { usePolling } from "../hooks/usePolling";
import { useLeaderboardRows } from "../hooks/useLeaderboardRows";
import { useLeaderboardView, type Order } from "../hooks/useLeaderboardView";
import { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import { useColumnPrefs } from "../hooks/useColumnPrefs";
import { useColumnEdits } from "../hooks/useColumnEdits";
import { useBoardSelection } from "../hooks/useBoardSelection";
import { useBoardGrouping } from "../hooks/useBoardGrouping";
import { useInnerRuns } from "../hooks/useInnerRuns";
import { foldState, isPending, topRows, treeRows } from "../util/sweepTree";
import BoardTabs, { BOARD_PANEL_ID, boardTabId } from "./BoardTabs";
import LeaderboardChartsPanel from "./LeaderboardChartsPanel";
import LeaderboardSelectionBar from "./LeaderboardSelectionBar";
import LeaderboardTable, { IDX_SORT, TIMESTAMP_SORT } from "./LeaderboardTable";
import { DATE_SORT_OF } from "./leaderboardColumns";
import LeaderboardToolbar from "./LeaderboardToolbar";
import BoardHead, { runCountText } from "./BoardHead";
import BoardCaption, { BOARD_CAPTION_ID } from "./BoardCaption";
import { useCanCreateRun } from "../shell/useAppExists";
import { useAppStatus } from "../shell/useShellData";
import AttentionStrip from "../components/AttentionStrip";
import { LiveText } from "../components/LiveStatus";
import { NARROW_QUERY, useMediaQuery } from "../hooks/useMediaQuery";
import { queryHelpData } from "../util/queryHelp";

const topLevel = (rows: readonly ExperimentRow[]) => topRows(rows, false).length;

const NEWEST_FIRST = new Set([TIMESTAMP_SORT, IDX_SORT, ...Object.values(DATE_SORT_OF)]);

/** A column's best-first direction: newest first for time, else its goal's.
 *  When the goal is unknown (null), default to desc (high first). */
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
  const narrow = useMediaQuery(NARROW_QUERY);
  const schema = useMetricsSchema(ws, app);
  const facets = useFacets(ws, app);
  const grouping = useBoardGrouping(ws, app, view);
  const status = useAppStatus(ws, app).data;
  const [paused, setPaused] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [brushed, setBrushed] = useState<Set<string> | null>(null);
  // Bumped when a saved view or the attention strip replaces the URL, so the
  // filter bar re-reads it.
  const [filterGen, setFilterGen] = useState(0);
  const resetFilter = () => setFilterGen((g) => g + 1);
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
  // The similar mode keeps the bar's tokens: the box holds its text.
  const similarQuery = combineQueries(serverQuery, statusClause(view.status));
  const similarFilter = useMemo(() => ({
    query: similarQuery || undefined,
    archived: view.archived || undefined,
  }), [similarQuery, view.archived]);
  const rows = data.rows;

  // Keep refreshing on our own while a run is still in flight (until paused),
  // at the cadence its heartbeat can actually move the status at.
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
  const all = useMemo(() => rows ?? [], [rows]);
  const { expanded } = view;
  const inner = useInnerRuns(ws, app, all, expanded, filter);
  const { refresh: refreshRows } = data;
  const { refresh: refreshInner } = inner;
  const refresh = useCallback(() => { refreshInner(); return refreshRows(); }, [refreshRows, refreshInner]);
  usePolling(refresh, pollIntervalMs(heartbeatSec), anyRunning && !paused);

  const base = `/ws/${ws}/app/${app}`;
  const colPrefs = useColumnPrefs(`${ws}/${app}`);
  const [tableWidth, setTableWidth] = useState(0);
  const cols = useLeaderboardColumns(
    rows, schema, view.hidden, base, facets, view.colOrder, view.pinned, colPrefs, tableWidth, view.shown,
  );
  const columnEdits = useColumnEdits(view, cols, colPrefs);
  const queryHelp = useMemo(() => queryHelpData({
    facets: cols.suggestFacets, branches: facets?.branches ?? [], rows: all, schema,
    primary: view.sort ?? cols.primary ?? cols.visibleMetrics[0],
  }), [cols.suggestFacets, facets, all, schema, view.sort, cols.primary, cols.visibleMetrics]);

  const charting = view.tab === "charts";
  // A brush in the parallel view (Charts tab) narrows the table.
  const brush = charting && view.chart === "parallel" ? brushed : null;
  const filtered = Boolean(view.query || view.status || view.search || view.branch || view.archived);
  // Inner runs sit under their outer, shown only once it is unfolded.
  const keep = useMemo(() => (brush ? (r: ExperimentRow) => brush.has(r.verstr) : undefined), [brush]);
  const top = useMemo(
    () => rows && topRows(rows, filtered).filter((r) => keep?.(r) ?? true), [rows, filtered, keep],
  );
  const tableItems = useMemo(
    () => top && treeRows(top, expanded, inner.innerOf, keep), [top, expanded, inner.innerOf, keep],
  );
  const tableRows = useMemo(
    () => tableItems?.filter((r): r is ExperimentRow => !isPending(r)),
    [tableItems],
  );
  const collapsedOf = useCallback((r: ExperimentRow) => foldState(r, expanded), [expanded]);
  const { toggleExpanded } = view;
  const onFold = useCallback((r: ExperimentRow) => toggleExpanded(r.verstr), [toggleExpanded]);
  const selection = useBoardSelection(ws, app, filter, tableRows ?? [], view, () => { refresh(); });

  const onPrefetch = useCallback(
    (verstr: string) => { prefetchRun(client, ws, app, verstr); },
    [client, ws, app],
  );
  const sortState = {
    sort: view.sort,
    order: view.sort ? view.order ?? bestOrder(schema, view.sort) : null,
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

  const empty = rows !== undefined && rows.length === 0 && !filtered;
  const sortLabel = view.sort ?? cols.primary;
  // Inner runs shown under an open outer do not count as runs on the board.
  const shownTop = top?.length ?? 0;

  return (
    <>
      <BoardHead
        title={appName}
        count={runCountText({
          loading: rows === undefined, filtered, loaded: all.length, total: data.total,
          shownTop, loadedTop: topLevel(all),
        })}
        live={narrow && anyRunning && <LiveText paused={paused} updatedAt={data.updatedAt} />}
        actions={!empty && (
          <LeaderboardToolbar
            ws={ws} app={app} view={view} cols={cols} grouping={grouping}
            onViewApplied={resetFilter}
            onResetColumns={colPrefs.customized ? colPrefs.reset : undefined}
          />
        )}
      />

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
          <AttentionStrip status={status} onFollow={resetFilter} />

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
            help={queryHelp}
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
                  rows={tableItems}
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
                  describedBy={BOARD_CAPTION_ID}
                />
                <BoardCaption
                  sortLabel={sortLabel} reversed={sortState.reversed}
                  live={{ running: anyRunning, paused, updatedAt: data.updatedAt, onPaused: setPaused, onRefresh: refresh }}
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
