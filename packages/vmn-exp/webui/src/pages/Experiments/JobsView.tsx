/** The Jobs view (plan 23 W1, §3.1): one row per top-level run — a job with
 *  its progress, best, spread, size, failures, throughput and ETA, or a
 *  single run — the jobs or the single runs (Jobs | Single runs), filtered
 *  by the board's filter bar, sorted by the job sort keys and grouped into
 *  groups of jobs, a group over 50 opening as a filter (§3.4). */
import { useCallback, useMemo, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { appName as toAppName } from "../../api";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import NewExperiment from "../../components/NewExperiment";
import { useAddFilterClauses } from "../../hooks/useAddFilterClauses";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { prefetchRun } from "../../queries";
import { fmtCount, plural } from "../../util";
import { groupClause } from "../../util/groupClause";
import type { BoardGroup } from "../../util/groupItems";
import BoardGridTools from "../BoardGridTools";
import BoardCaption from "../BoardCaption";
import BoardHead from "../BoardHead";
import LeaderboardSelectionBar from "../LeaderboardSelectionBar";
import { EmptyBoard } from "./AllRunsView";
import JobsTable from "./JobsTable";
import JobsToolbar from "./JobsToolbar";
import { kindNoun, kindQuery, useJobsKind, type JobsKind } from "./jobsKind";
import { useJobsBoard } from "./useJobsBoard";

/** `20 jobs`, `19,580 single runs`; listing every top-level run, `14 jobs ·
 *  3 single runs` once every row is loaded, else the total. */
function countText(loading: boolean, rows: { job?: unknown }[], total: number, kind: JobsKind | null): string {
  if (loading) return "loading jobs…";
  if (kind) return plural(total, kindNoun(kind));
  if (rows.length < total) return `${fmtCount(total)} top-level runs`;
  const jobs = rows.filter((r) => r.job).length;
  const singles = rows.length - jobs;
  return [jobs && plural(jobs, "job"), singles && plural(singles, "single run")].filter(Boolean).join(" · ") || "0 runs";
}

/** `No jobs match the filters.`, `No single runs yet.` */
const emptyText = (kind: JobsKind | null, filtered: boolean) =>
  filtered ? `No ${kindNoun(kind)}s match the filters.` : `No ${kindNoun(kind)}s yet.`;

export default function JobsView({ ws, app, views }: { ws: string; app: string; views?: ReactNode }) {
  const appName = toAppName(app);
  const client = useQueryClient();
  const view = useLeaderboardView();
  const kind = useJobsKind(ws, app);
  const board = useJobsBoard(ws, app, view, kind.top);
  const { data, rows, selection, live } = board;
  const base = `/ws/${ws}/app/${app}`;
  const ctx = useMemo(() => ({ runBase: base, metric: board.metric, goal: board.goal }), [base, board.metric, board.goal]);
  // A saved view or a big group replaces the URL: the filter bar re-reads it.
  const { gen: filterGen, resetFilter, openGroup } = useAddFilterClauses(view);
  const field = data.grouped ? board.group : null;
  const asFilter = useMemo(() => field ? {
    clauseOf: (g: BoardGroup) => g.clause ?? groupClause(field, g.key), onFilter: openGroup,
  } : undefined, [field, openGroup]);
  const onPrefetch = useCallback((v: string) => { prefetchRun(client, ws, app, v); }, [client, ws, app]);

  if (data.pageError) return <div className="error">{data.pageError}</div>;
  const loading = data.items === undefined;
  // With the switch shown the app has jobs: an empty side is no empty app.
  // Grouped, a group opened as a filter holds no rows: the total counts it.
  const empty = !loading && rows.length === 0 && data.total === 0 && !board.filtered && !kind.kind;

  return (
    <>
      <BoardHead
        title={appName}
        count={countText(loading, rows, data.total, kind.kind)}
        views={views}
        actions={!empty && <JobsToolbar ws={ws} app={app} view={view} board={board} kind={kind} onViewApplied={resetFilter} />}
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
          <JobsTable
            items={data.items} ctx={ctx} sort={board.sort}
            selected={view.selected} density={view.density}
            headerCheck={{ state: selection.headerCheck, onToggle: selection.toggleAll, label: "Select all visible jobs" }}
            emptyText={emptyText(kind.kind, board.filtered)}
            groups={{
              noun: kind.kind === "jobs" ? "job" : "run", asFilter,
              onFold: view.toggleCollapsed, onMore: data.loadGroup,
              checkOf: selection.checkOf, onCheck: selection.toggleRows,
            }}
            hasMore={data.hasMore} onNearEnd={data.loadMore} visibleRef={data.visibleRef}
            onToggle={selection.toggle} onPrefetch={onPrefetch} onClearAnchor={selection.clearAnchor}
          />
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
          <LeaderboardSelectionBar
            selected={[...view.selected]} total={data.total} base={base}
            showUnarchive={view.archived} archiving={selection.archiving} archiveError={selection.archiveError}
            onClear={() => view.setSelected([])} onSelectAll={selection.selectAll} onArchive={selection.archive}
          />
        </>
      )}
    </>
  );
}
