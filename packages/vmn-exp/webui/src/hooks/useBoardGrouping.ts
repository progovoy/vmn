/** The board's grouping (plan 22 G2, G10): the URL's `group=`/`agg=` over
 *  the defaults — grouped by parent run when the app has parented runs, the
 *  aggregate from the app's conf `experiment.ui.group_aggregate`, else mean. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { api } from "../api";
import { facetsQuery } from "../queries";
import {
  LINK_GROUPS, confAggregate, defaultGroup as defaultGroupOf, groupFields,
  type Aggregate, type GroupBy,
} from "../util/groupBy";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = Pick<ReturnType<typeof useLeaderboardView>, "groupParam" | "aggParam" | "setGroup" | "setAggregate">;

/** The app's default aggregate; mean until (or unless) its conf says otherwise. */
function useConfAggregate(ws: string, app: string): Aggregate {
  const client = useQueryClient();
  const q = useQuery({
    queryKey: ["app-config", ws, app],
    queryFn: () => api.config(ws, app),
    staleTime: 60_000,
  }, client);
  return confAggregate(q.data?.conf);
}

export function useBoardGrouping(ws: string, app: string, view: View) {
  const client = useQueryClient();
  const facets = useQuery(facetsQuery(ws, app), client);
  const defaultAggregate = useConfAggregate(ws, app);
  // Unknown (null) until the facets answer; a failed answer means ungrouped,
  // also while it is asked again (Back to the board paints at once).
  const failed = facets.isError || facets.errorUpdatedAt > 0;
  const defaultGroup: GroupBy | null = facets.data
    ? defaultGroupOf(facets.data) : failed ? defaultGroupOf(null) : null;
  const group = view.groupParam ?? defaultGroup;
  const fields = useMemo(() => groupFields(facets.data), [facets.data]);

  const { setGroup: writeGroup, setAggregate: writeAggregate } = view;
  const setGroup = useCallback(
    (g: GroupBy) => writeGroup(g, defaultGroup ?? defaultGroupOf(null)), [writeGroup, defaultGroup],
  );
  const setAggregate = useCallback(
    (a: Aggregate) => writeAggregate(a, defaultAggregate), [writeAggregate, defaultAggregate],
  );

  return {
    group,
    defaultGroup,
    /** What the board shows; what it sends is `aggregateInUrl` (else the
     *  server applies the same conf default). */
    aggregate: view.aggParam ?? defaultAggregate,
    aggregateInUrl: view.aggParam,
    defaultAggregate,
    links: LINK_GROUPS,
    fields,
    setGroup,
    setAggregate,
  };
}
