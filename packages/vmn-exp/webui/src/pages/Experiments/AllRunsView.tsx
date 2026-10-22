import { useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { appName as toAppName } from "../../api";
import ReportsUsing from "../../components/ReportsUsing";
import { combineQueries, statusClause } from "../../util/searchQuery";
import type { ExperimentRow } from "../../types";
import NewExperiment from "../../components/NewExperiment";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import SimilarSearch from "../../components/SimilarSearch";
import { useAddFilterClauses } from "../../hooks/useAddFilterClauses";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { BIG_GROUP } from "../../util/groupClause";
import BoardTabs, { BOARD_PANEL_ID, boardTabId } from "../BoardTabs";
import LeaderboardChartsPanel from "../LeaderboardChartsPanel";
import { useTrayBoard } from "../SelectionTrayHost";
import { isGroupCountId } from "../../util/groupCountSort";
import LeaderboardToolbar from "../LeaderboardToolbar";
import BoardHead, { runCountText } from "../BoardHead";
import RunsBoardGrid from "../RunsBoardGrid";
import StaleRows from "../../components/StaleRows";
import { useRunsBoard } from "../../hooks/useRunsBoard";
import { useCanCreateRun } from "../../shell/useAppExists";
import { useAppStatus } from "../../shell/useShellData";
import AttentionStrip from "../../components/AttentionStrip";
import { LiveText } from "../../components/LiveStatus";
import { NARROW_QUERY, useMediaQuery } from "../../hooks/useMediaQuery";

/** The runs no other run launched (the subtitle's `N runs`). */
const topLevel = (rows: readonly ExperimentRow[]) => rows.filter((r) => !r.depth).length;

/** An existing app without runs: the CLI line, plus a New run button where a
 *  run can be created here (a known app, a writable git workspace). */
export function EmptyBoard({ ws, app, appName, onCreate }: {
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
  return <AllRunsView key={`${ws}/${app}`} ws={ws} app={app} />;
}

/** The All runs view (plan 23 W1): plan 22's board of every run. Inside the
 *  experiments page, *views* is the Jobs | All runs switch and *onJobs*
 *  opens the Jobs view: the board's "parent run" grouping (§3.4). */
export function AllRunsView({ ws, app, views, onJobs }: {
  ws: string; app: string; views?: ReactNode; onJobs?: () => void;
}) {
  const appName = toAppName(app);
  const view = useLeaderboardView();
  const narrow = useMediaQuery(NARROW_QUERY);
  const status = useAppStatus(ws, app).data;
  const [paused, setPaused] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [brushed, setBrushed] = useState<Set<string> | null>(null);
  // A saved view, the attention strip or a big group replaces the URL: the
  // filter bar re-reads it.
  const { gen: filterGen, resetFilter, openGroup } = useAddFilterClauses(view);
  // The search box's "similar" mode text; null shows the table.
  const [similarText, setSimilarText] = useState<string | null>(null);

  const charting = view.tab === "charts";
  // A brush in the parallel view (Charts tab) narrows the table.
  const brush = charting && view.chart === "parallel" ? brushed : null;
  const keep = useMemo(() => (brush ? (r: ExperimentRow) => brush.has(r.verstr) : undefined), [brush]);
  const board = useRunsBoard(ws, app, view, {
    paused, onParent: onJobs, keep, openGroup: { over: BIG_GROUP, onOpen: openGroup },
  });
  const { data, facets, filter, cols, colPrefs, schema, rows, all, tableRows, filtered } = board;
  useTrayBoard({
    total: data.total, showUnarchive: view.archived, onSelectAll: () => void board.selection.selectAll(),
    onArchived: board.refresh,
  });
  // The similar mode keeps the bar's tokens: the box holds its text.
  const similarQuery = combineQueries(board.serverQuery, statusClause(view.status));
  const similarFilter = useMemo(() => ({
    query: similarQuery || undefined,
    archived: view.archived || undefined,
  }), [similarQuery, view.archived]);

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
  const { sortLabel, anyRunning } = board;
  // `vmn-exp list` sorts runs, not groups.
  const cliSort = isGroupCountId(sortLabel) ? null : sortLabel;
  const shownTop = topLevel(tableRows ?? []);
  // Groups hold only their first rows: the facets count the board's runs.
  const wholeBoard = data.grouped && rows !== undefined && !filtered && facets !== null;

  return (
    <>
      <BoardHead
        title={appName}
        count={runCountText(wholeBoard ? {
          loading: false, filtered, loaded: data.total, total: data.total,
          shownTop, loadedTop: Math.max(0, data.total - facets.parented),
        } : {
          loading: rows === undefined, filtered, loaded: all.length, total: data.total,
          shownTop, loadedTop: topLevel(all),
        })}
        live={narrow && anyRunning && <LiveText paused={paused} updatedAt={data.updatedAt} />}
        views={views}
        actions={!empty && (
          <LeaderboardToolbar
            ws={ws} app={app} view={view} cols={cols} grouping={board.grouping}
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
            help={board.queryHelp}
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
                    onBrushed={setBrushed} grouping={board.chartGrouping} selected={view.selected}
                  />
                )}

                <StaleRows stale={data.stale} error={data.staleError}>
                  <RunsBoardGrid board={board} view={view} flash={flash} paused={paused} onPaused={setPaused} />
                </StaleRows>
              </div>
            </>
          )}
          <ReportsUsing ws={ws} app={appName} />
          <div className="cli-card">
            vmn-exp list {appName}{cliSort ? ` --sort ${cliSort}` : ""}
          </div>
        </>
      )}
    </>
  );
}
