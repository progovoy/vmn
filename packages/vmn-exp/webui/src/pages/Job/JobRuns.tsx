/** A job's Runs tab (plan 23 W3, §3.2): plan 22's board scoped to the job's
 *  subtree (`scope=` on every list, columns and facets request), with a facet
 *  sidebar, Group by inside the job (a group of more than 50 runs opens as a
 *  filter, §3.4) and selection by query. The URL keeps `tab=runs` beside the
 *  board's own params. A search has a `search all runs` link that drops the
 *  scope (plan 23 W11). */
import FacetSidebar from "../../components/FacetSidebar";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import { useAddFilterClauses } from "../../hooks/useAddFilterClauses";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { useRunsBoard } from "../../hooks/useRunsBoard";
import { Link } from "react-router-dom";
import { plural } from "../../util";
import { allRunsHref, hasSearch } from "../../util/searchScope";
import { BIG_GROUP } from "../../util/groupClause";
import { useTrayBoard } from "../SelectionTrayHost";
import LeaderboardToolbar from "../LeaderboardToolbar";
import RunsBoardGrid from "../RunsBoardGrid";

export default function JobRuns({ ws, app, verstr, name, paused, onPaused, onLive }: {
  ws: string; app: string; verstr: string;
  /** The job's name, naming its selected queries in the tray. */
  name?: string;
  paused: boolean;
  onPaused: (paused: boolean) => void;
  /** Told of each live change of the subtree (the job's rollup refreshes). */
  onLive?: () => unknown;
}) {
  const view = useLeaderboardView();
  // A facet or a group writes the filters: the bar re-reads them.
  const { gen: filterGen, resetFilter, addClauses, openGroup } = useAddFilterClauses(view);

  const board = useRunsBoard(ws, app, view, {
    paused, scope: verstr, scopeLabel: name, onLive, openGroup: { over: BIG_GROUP, onOpen: openGroup },
  });
  const { data, cols, selection, facets } = board;
  useTrayBoard({
    total: data.total, showUnarchive: view.archived, onSelectAll: () => void selection.selectAll(data.total),
    matching: selection.matching, uncapped: selection.uncapped, onArchived: board.refresh,
  });

  if (data.pageError) return <div className="error">{data.pageError}</div>;
  return (
    <div className="job-runs">
      <FacetSidebar
        ws={ws} app={app} scope={verstr} query={board.serverQuery} status={view.status}
        onAdd={(clauses) => addClauses(clauses)}
      />
      <div className="job-runs-main">
        <div className="job-runs-head">
          <p className="page-sub job-runs-count">
            {board.rows === undefined ? "loading runs…" : plural(data.total, "run")}
            {hasSearch(view) && <> · <Link to={allRunsHref(board.base, view)}>search all runs</Link></>}
          </p>
          <LeaderboardToolbar
            ws={ws} app={app} view={view} cols={cols} grouping={board.grouping} job={verstr}
            onViewApplied={resetFilter}
            onResetColumns={board.colPrefs.customized ? board.colPrefs.reset : undefined}
          />
        </div>
        <LeaderboardFilter
          key={filterGen}
          branches={facets?.branches ?? null}
          rows={facets ? undefined : board.all}
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
        <RunsBoardGrid board={board} view={view} paused={paused} onPaused={onPaused} />
      </div>
    </div>
  );
}
