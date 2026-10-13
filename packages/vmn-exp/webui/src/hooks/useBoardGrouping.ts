/** The board's grouping (plan 22 G2): the URL's `group=` over the default —
 *  grouped by parent run when the app has parented runs. The aggregate a
 *  grouped board shows is the server's (useBoardAggregate, F3). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { facetsQuery } from "../queries";
import {
  LINK_GROUPS, NO_GROUP, defaultGroup as defaultGroupOf, groupFields, type GroupBy,
} from "../util/groupBy";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = Pick<ReturnType<typeof useLeaderboardView>, "groupParam" | "aggParam" | "setGroup">;

/** With *onParent* (the experiments page's All runs view, plan 23 §3.4) the
 *  board never groups by parent run on its own, and picking that grouping
 *  calls *onParent* instead: it is the Jobs view.
 *
 *  With *scope* (a job's Runs tab, §3.4) the board groups inside the job:
 *  ungrouped by default, by fields only (the failure signature among them),
 *  offered from the job's own facets. */
export function useBoardGrouping(ws: string, app: string, view: View, onParent?: () => void, scope?: string) {
  const client = useQueryClient();
  const facets = useQuery(facetsQuery(ws, app, scope ? { scope } : undefined), client);
  // Unknown (null) until the facets answer; a failed answer means ungrouped,
  // also while it is asked again (Back to the board paints at once).
  const failed = facets.isError || facets.errorUpdatedAt > 0;
  const defaultGroup: GroupBy | null = onParent || scope ? NO_GROUP : facets.data
    ? defaultGroupOf(facets.data) : failed ? defaultGroupOf(null) : null;
  const group = view.groupParam ?? defaultGroup;
  const fields = useMemo(() => groupFields(facets.data, Boolean(scope)), [facets.data, scope]);

  const { setGroup: writeGroup } = view;
  const setGroup = useCallback(
    (g: GroupBy) => (g === "parent" && onParent ? onParent() : writeGroup(g, defaultGroup ?? defaultGroupOf(null))),
    [writeGroup, defaultGroup, onParent],
  );

  return {
    group,
    defaultGroup,
    /** What the board sends; absent, the server applies the app's conf default. */
    aggregateInUrl: view.aggParam,
    links: scope ? [] : LINK_GROUPS,
    fields,
    setGroup,
  };
}
