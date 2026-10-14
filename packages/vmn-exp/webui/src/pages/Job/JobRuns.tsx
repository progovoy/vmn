/** A job's Runs tab (plan 23 W3, §3.2): plan 22's board scoped to the job's
 *  subtree (`scope=` on every list, columns and facets request), with a facet
 *  sidebar, Group by inside the job (a group of more than 50 runs opens as a
 *  filter, §3.4) and selection by query. The URL keeps `tab=runs` beside the
 *  board's own params. A search has a `search all runs` link that drops the
 *  scope (plan 23 W11). */
import { useCallback, useState } from "react";
import FacetSidebar from "../../components/FacetSidebar";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { useRunsBoard } from "../../hooks/useRunsBoard";
import { Link } from "react-router-dom";
import { plural } from "../../util";
import { allRunsHref, hasSearch } from "../../util/searchScope";
import { BIG_GROUP, addFilterClause } from "../../util/groupClause";
import LeaderboardSelectionBar from "../LeaderboardSelectionBar";
import LeaderboardToolbar from "../LeaderboardToolbar";
import RunsBoardGrid from "../RunsBoardGrid";

export default function JobRuns({ ws, app, verstr, paused, onPaused, onLive }: {
  ws: string; app: string; verstr: string;
  paused: boolean;
  onPaused: (paused: boolean) => void;
  /** Told of each live change of the subtree (the job's rollup refreshes). */
  onLive?: () => unknown;
}) {
  const view = useLeaderboardView();
  // Bumped when a facet or a group writes the filters, so the bar re-reads them.
  const [filterGen, setFilterGen] = useState(0);
  const resetFilter = () => setFilterGen((g) => g + 1);

  const { setFilters, status, query, search, branch } = view;
  const addClauses = useCallback((clauses: string[], ungroup = false) => {
    const next = clauses.reduce(addFilterClause, { status, query, search, branch });
    setFilters(next, ungroup);
    setFilterGen((g) => g + 1);
  }, [setFilters, status, query, search, branch]);
  const openGroup = useCallback((clause: string) => addClauses([clause], true), [addClauses]);

  const board = useRunsBoard(ws, app, view, {
    paused, scope: verstr, onLive, openGroup: { over: BIG_GROUP, onOpen: openGroup },
  });
  const { data, cols, selection, facets } = board;

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
      <LeaderboardSelectionBar
        selected={[...view.selected]}
        total={data.total}
        base={board.base}
        showUnarchive={view.archived}
        archiving={selection.archiving}
        archiveError={selection.archiveError}
        onClear={() => view.setSelected([])}
        onSelectAll={() => selection.selectAll(data.total)}
        onArchive={selection.archive}
        matching={selection.matching}
        onPreview={selection.preview}
        uncapped={selection.uncapped}
      />
    </div>
  );
}
