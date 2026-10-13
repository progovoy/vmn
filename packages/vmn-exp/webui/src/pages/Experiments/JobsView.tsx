/** The Jobs view (plan 23 W1, §3.1): one row per top-level run — a job with
 *  its progress, best, spread, size, failures, throughput and ETA, or a
 *  single run — filtered by the board's filter bar, sorted by the job sort
 *  keys and grouped into groups of jobs (§3.4). */
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { appName as toAppName } from "../../api";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import NewExperiment from "../../components/NewExperiment";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { prefetchRun } from "../../queries";
import { fmtCount, plural } from "../../util";
import BoardGridTools from "../BoardGridTools";
import BoardCaption from "../BoardCaption";
import BoardHead from "../BoardHead";
import LeaderboardSelectionBar from "../LeaderboardSelectionBar";
import { EmptyBoard } from "./AllRunsView";
import JobsTable from "./JobsTable";
import JobsToolbar from "./JobsToolbar";
import { useJobsBoard } from "./useJobsBoard";

/** `14 jobs · 3 single runs` once every row is loaded, else the total. */
function countText(loading: boolean, rows: { job?: unknown }[], total: number): string {
  if (loading) return "loading jobs…";
  if (rows.length < total) return `${fmtCount(total)} top-level runs`;
  const jobs = rows.filter((r) => r.job).length;
  const singles = rows.length - jobs;
  return [jobs && plural(jobs, "job"), singles && plural(singles, "single run")].filter(Boolean).join(" · ") || "0 runs";
}

export default function JobsView({ ws, app, views }: { ws: string; app: string; views?: ReactNode }) {
  const appName = toAppName(app);
  const client = useQueryClient();
  const view = useLeaderboardView();
  const board = useJobsBoard(ws, app, view);
  const { data, rows, selection, live } = board;
  const base = `/ws/${ws}/app/${app}`;
  const ctx = useMemo(() => ({ runBase: base, metric: board.metric, goal: board.goal }), [base, board.metric, board.goal]);
  // Bumped when a saved view replaces the URL, so the filter bar re-reads it.
  const [filterGen, setFilterGen] = useState(0);
  const onPrefetch = useCallback((v: string) => { prefetchRun(client, ws, app, v); }, [client, ws, app]);

  if (data.pageError) return <div className="error">{data.pageError}</div>;
  const loading = data.items === undefined;
  const empty = !loading && rows.length === 0 && !board.filtered;

  return (
    <>
      <BoardHead
        title={appName}
        count={countText(loading, rows, data.total)}
        views={views}
        actions={!empty && <JobsToolbar ws={ws} app={app} view={view} board={board} onViewApplied={() => setFilterGen((g) => g + 1)} />}
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
            groups={{
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
          <div className="cli-card">vmn-exp list {appName} --query &apos;depth = 0&apos;</div>
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
