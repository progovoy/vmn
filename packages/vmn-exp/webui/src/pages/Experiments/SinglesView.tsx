/** The Single runs view (plan 23 §3.1): the top-level runs without children
 *  (`top=singles`), on the All runs board's table and default columns
 *  (status, experiment, goal metrics, varying params, when) — a single run
 *  has no progress, best or spread to show. Newest first unless sorted. */
import { useState, type ReactNode } from "react";
import { appName as toAppName } from "../../api";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import NewExperiment from "../../components/NewExperiment";
import { useAddFilterClauses } from "../../hooks/useAddFilterClauses";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { useRunsBoard } from "../../hooks/useRunsBoard";
import { useAppStatus } from "../../shell/useShellData";
import { plural } from "../../util";
import { BIG_GROUP } from "../../util/groupClause";
import { freshnessShort } from "../../util/freshness";
import { indexingText } from "../../util/indexing";
import BoardHead from "../BoardHead";
import LeaderboardToolbar from "../LeaderboardToolbar";
import RunsBoardGrid from "../RunsBoardGrid";
import { useTrayBoard } from "../SelectionTrayHost";
import { kindNoun, kindQuery } from "./jobsKind";

const NOUN = kindNoun("singles");

export default function SinglesView({ ws, app, views, onJobs }: {
  ws: string; app: string; views?: ReactNode;
  /** Picking the "parent run" grouping opens the Outer runs view. */
  onJobs: () => void;
}) {
  const appName = toAppName(app);
  const view = useLeaderboardView();
  const status = useAppStatus(ws, app).data;
  const indexing = status?.indexing;
  const [paused, setPaused] = useState(false);
  const { gen: filterGen, resetFilter, openGroup } = useAddFilterClauses(view);
  const board = useRunsBoard(ws, app, view, {
    paused, top: "singles", onParent: onJobs, openGroup: { over: BIG_GROUP, onOpen: openGroup },
  });
  const { data, facets, cols, colPrefs, rows, filtered } = board;
  useTrayBoard({
    total: data.total, showUnarchive: view.archived, onSelectAll: () => void board.selection.selectAll(),
    onArchived: board.refresh,
  });

  if (data.pageError) return <div className="error">{data.pageError}</div>;
  const loading = rows === undefined;
  const count = loading ? `loading ${NOUN}s…` : plural(data.total, NOUN);

  return (
    <>
      <BoardHead
        title={appName}
        count={[count, indexingText(indexing), freshnessShort(status?.freshness)].filter(Boolean).join(" · ")}
        views={views}
        actions={(
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
          onCreated={() => { view.openCreate(false); data.refresh(); }}
        />
      )}
      <LeaderboardFilter
        key={filterGen}
        rows={facets ? undefined : rows}
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
        help={board.queryHelp}
      />
      {!loading && rows.length === 0 && (
        <p className="empty">{filtered ? `No ${NOUN}s match the filters.` : `No ${NOUN}s yet.`}</p>
      )}
      <RunsBoardGrid board={board} view={view} paused={paused} onPaused={setPaused} />
      <div className="cli-card">vmn-exp list {appName} --query &apos;{kindQuery("singles")}&apos;</div>
    </>
  );
}
