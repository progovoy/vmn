/** The Jobs view (plan 23 W1, §3.1): one row per top-level run — a job with
 *  its progress, best, spread, size, failures, throughput and ETA, or a
 *  single run — the jobs or the single runs (*kind*, the page's switch), filtered
 *  by the board's filter bar, sorted by the job sort keys and grouped into
 *  groups of jobs, a group over 50 opening as a filter (§3.4). */
import { useMemo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { appName as toAppName } from "../../api";
import AttentionStrip from "../../components/AttentionStrip";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import NewExperiment from "../../components/NewExperiment";
import NewRowsBar from "../../components/NewRowsBar";
import StaleRows from "../../components/StaleRows";
import { useAddFilterClauses } from "../../hooks/useAddFilterClauses";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { fmtCount, plural } from "../../util";
import type { BoardGroup } from "../../util/groupItems";
import BoardGridTools from "../BoardGridTools";
import BoardCaption from "../BoardCaption";
import BoardHead from "../BoardHead";
import { useTrayBoard } from "../SelectionTrayHost";
import { EmptyBoard } from "./AllRunsView";
import { allRunsSearch } from "./experimentsView";
import JobsMatchLine from "./JobsMatchLine";
import JobsTable from "./JobsTable";
import JobsToolbar from "./JobsToolbar";
import { kindNoun, kindQuery, type JobsKind, type JobsKindState } from "./jobsKind";
import { useJobsBoard } from "./useJobsBoard";
import { useAppStatus } from "../../shell/useShellData";
import { freshnessShort } from "../../util/freshness";
import { indexingText } from "../../util/indexing";

/** `20 jobs`, `19,580 single runs`; listing every top-level run, `14 jobs ·
 *  3 single runs` once every row is loaded, else the total. */
function countText(loading: boolean, rows: { job?: unknown }[], total: number, kind: JobsKind | null): string {
  if (loading) return `loading ${kindNoun(kind ?? "jobs")}s…`;
  if (kind) return plural(total, kindNoun(kind));
  if (rows.length < total) return `${fmtCount(total)} top-level runs`;
  const jobs = rows.filter((r) => r.job).length;
  const singles = rows.length - jobs;
  return [jobs && plural(jobs, "outer run"), singles && plural(singles, "single run")].filter(Boolean).join(" · ") || "0 runs";
}

/** `No jobs match the filters.`, `No single runs yet.` */
const emptyText = (kind: JobsKind | null, filtered: boolean) =>
  filtered ? `No ${kindNoun(kind)}s match the filters.` : `No ${kindNoun(kind)}s yet.`;

export default function JobsView({ ws, app, views, kind, onAll }: {
  ws: string; app: string; views?: ReactNode; kind: JobsKindState;
  /** Open the All runs view. */
  onAll: () => void;
}) {
  const appName = toAppName(app);
  const view = useLeaderboardView();
  const board = useJobsBoard(ws, app, view, kind.top);
  const { data, rows, selection, live } = board;
  // A store's index still loading: the rows so far are the newest runs.
  const status = useAppStatus(ws, app).data;
  const indexing = status?.indexing;
  const base = `/ws/${ws}/app/${app}`;
  const attention = status?.attention;
  const ctx = useMemo(() => ({ runBase: base, metric: board.metric, goal: board.goal, search: board.search, attention }),
    [base, board.metric, board.goal, board.search, attention]);
  // The strip counts runs, not outer runs: its parts open All runs filtered.
  const { search: here } = useLocation();
  // A saved view or a big group replaces the URL: the filter bar re-reads it.
  const { gen: filterGen, resetFilter, openGroup } = useAddFilterClauses(view);
  const asFilter = useMemo(() => data.grouped ? {
    clauseOf: (g: BoardGroup) => g.clause, onFilter: openGroup,
  } : undefined, [data.grouped, openGroup]);
  useTrayBoard({
    total: data.total, showUnarchive: view.archived, onSelectAll: () => void selection.selectAll(),
    onArchived: data.refresh,
  });

  if (data.pageError) return <div className="error">{data.pageError}</div>;
  const loading = data.items === undefined;
  // With the switch shown the app has jobs: an empty side is no empty app.
  // Grouped, a group opened as a filter holds no rows: the total counts it.
  const empty = !loading && rows.length === 0 && data.total === 0 && !board.filtered && !kind.kind;

  return (
    <>
      <BoardHead
        title={appName}
        count={[countText(loading, rows, data.total, kind.kind), indexingText(indexing), freshnessShort(status?.freshness)]
          .filter(Boolean).join(" · ")}
        views={views}
        actions={!empty && <JobsToolbar ws={ws} app={app} view={view} board={board} onViewApplied={resetFilter} onAll={onAll} />}
      />
      {view.creating && (
        <NewExperiment
          ws={ws} app={app} appName={appName}
          onClose={() => view.openCreate(false)}
          onCreated={() => { view.openCreate(false); data.refresh(); }}
        />
      )}
      {empty ? (
        !view.creating && <EmptyBoard ws={ws} app={app} appName={appName} onCreate={() => view.openCreate(true)} />
      ) : (
        <>
          <AttentionStrip status={status} from={allRunsSearch(here)} />
          <LeaderboardFilter
            key={filterGen}
            branches={board.facets?.branches ?? null}
            rows={board.facets ? undefined : rows}
            facets={{ metric_keys: board.facets?.metric_keys, param_keys: board.facets?.param_keys }}
            initial={{ search: view.search, branch: view.branch, status: view.status, query: view.query }}
            onStatusChange={view.setStatus}
            onQueryChange={view.setQuery}
            onSearchChange={view.setSearch}
            onBranchChange={view.setBranch}
            queryError={data.queryError}
            archived={view.archived}
            onArchivedChange={view.setArchived}
          />
          <JobsMatchLine matches={data.matches} appBase={base} search={board.search} />
          <NewRowsBar pending={data.pending} noun={kind.kind === "jobs" ? "outer run" : "run"} onShow={data.showNew} />
          <StaleRows stale={data.stale} error={data.staleError}>
            <JobsTable
              items={data.items} ctx={ctx} sort={board.sort}
              selected={view.selected} density={view.density}
              headerCheck={{ state: selection.headerCheck, onToggle: selection.toggleAll, label: "Select all visible outer runs" }}
              emptyText={emptyText(kind.kind, board.filtered)}
              groups={{
                noun: kind.kind === "jobs" ? "outer run" : "run", asFilter,
                onFold: view.toggleCollapsed, onMore: data.loadGroup,
                checkOf: selection.checkOf, onCheck: selection.toggleRows,
              }}
              hasMore={data.hasMore} onNearEnd={data.loadMore} visibleRef={data.visibleRef} viewportRef={data.viewportRef}
              onToggle={selection.toggle} onClearAnchor={selection.clearAnchor}
            />
          </StaleRows>
          <BoardCaption
            sortLabel={null} reversed={false} legend={false}
            live={{ running: live.running, paused: live.paused, updatedAt: data.updatedAt, onPaused: live.setPaused, onRefresh: data.refresh }}
            tools={<BoardGridTools density={view.density} onDensity={view.setDensity} />}
          />
          {!loading && data.hasMore && (
            <div className="load-more">
              <button onClick={data.loadMore}>{data.moreLabel}</button>
              {data.moreError && <span className="error">{data.moreError}</span>}
            </div>
          )}
          <div className="cli-card">vmn-exp list {appName} --query &apos;{kindQuery(kind.kind)}&apos;</div>
        </>
      )}
    </>
  );
}
