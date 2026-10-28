/** The Runs tab's tree layout (plan 28 N6): the tab's filter bar above the
 *  outer run's tree, which is asked for under the URL's filters and sort
 *  (status, query, search, branch, archived; the same URL params as the
 *  flat board, so switching layouts keeps them). */
import type { TreeFilter } from "../../apiTree";
import LeaderboardFilter from "../../components/LeaderboardFilter";
import { boardQuery } from "../../hooks/useBoardFilter";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { useFacets } from "../../queries";
import type { AttentionEntry } from "../../shell/contracts";
import { NO_GROUP } from "../../util/groupBy";
import { boardSort } from "../../util/groupCountSort";
import JobTree from "./JobTree";

type View = ReturnType<typeof useLeaderboardView>;

/** *view*'s filters and sort as the tree asks for them (no sort: the server's order). */
export function treeFilter(view: View): TreeFilter {
  const sort = boardSort(view.sort, NO_GROUP) ?? undefined;
  return {
    status: view.status || undefined,
    query: boardQuery(view) || undefined,
    sort,
    order: sort ? view.order : undefined,
    archived: view.archived || undefined,
  };
}

export default function JobTreeRuns({ ws, app, verstr, name, attention }: {
  ws: string; app: string; verstr: string; name?: string;
  attention?: readonly AttentionEntry[];
}) {
  const view = useLeaderboardView();
  const facets = useFacets(ws, app, { scope: verstr });
  return (
    <>
      <LeaderboardFilter
        branches={facets?.branches ?? null}
        facets={{ metric_keys: facets?.metric_keys, param_keys: facets?.param_keys }}
        initial={{ search: view.search, branch: view.branch, status: view.status, query: view.query }}
        onStatusChange={view.setStatus}
        onQueryChange={view.setQuery}
        onSearchChange={view.setSearch}
        onBranchChange={view.setBranch}
        archived={view.archived}
        onArchivedChange={view.setArchived}
      />
      <JobTree ws={ws} app={app} verstr={verstr} name={name} attention={attention} filter={treeFilter(view)} />
    </>
  );
}
