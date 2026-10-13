/** The board's grouping (plan 22 G2): the URL's `group=` over the default —
 *  grouped by parent run when the app has parented runs. The aggregate a
 *  grouped board shows is the server's (useBoardAggregate, F3). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { facetsQuery } from "../queries";
import { LINK_GROUPS, defaultGroup as defaultGroupOf, groupFields, type GroupBy } from "../util/groupBy";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = Pick<ReturnType<typeof useLeaderboardView>, "groupParam" | "aggParam" | "setGroup">;

export function useBoardGrouping(ws: string, app: string, view: View) {
  const client = useQueryClient();
  const facets = useQuery(facetsQuery(ws, app), client);
  // Unknown (null) until the facets answer; a failed answer means ungrouped,
  // also while it is asked again (Back to the board paints at once).
  const failed = facets.isError || facets.errorUpdatedAt > 0;
  const defaultGroup: GroupBy | null = facets.data
    ? defaultGroupOf(facets.data) : failed ? defaultGroupOf(null) : null;
  const group = view.groupParam ?? defaultGroup;
  const fields = useMemo(() => groupFields(facets.data), [facets.data]);

  const { setGroup: writeGroup } = view;
  const setGroup = useCallback(
    (g: GroupBy) => writeGroup(g, defaultGroup ?? defaultGroupOf(null)), [writeGroup, defaultGroup],
  );

  return {
    group,
    defaultGroup,
    /** What the board sends; absent, the server applies the app's conf default. */
    aggregateInUrl: view.aggParam,
    links: LINK_GROUPS,
    fields,
    setGroup,
  };
}
