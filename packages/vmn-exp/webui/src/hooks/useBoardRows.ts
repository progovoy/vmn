/** The board's rows (plan 22 G1, G4): the flat list of every run, or with a
 *  grouping the grouped payload's header rows and rows, as one shape. */
import { useMemo } from "react";
import type { GroupAggregate } from "../apiGroups";
import type { RowsFilter } from "../queries";
import type { ExperimentRow } from "../types";
import { plural } from "../util";
import { NO_GROUP, type GroupBy } from "../util/groupBy";
import { groupItems, type BoardItem } from "../util/groupItems";
import { useGroupedRows } from "./useGroupedRows";
import { useLeaderboardRows } from "./useLeaderboardRows";

/** *group* null (not known yet: the facets have not answered) fetches
 *  nothing; `none` is the flat list. *keep* narrows the rows on screen. */
export function useBoardRows(ws: string, app: string, filter: RowsFilter, grouping: {
  group: GroupBy | null; aggregateInUrl: GroupAggregate | null; collapsed: ReadonlySet<string>;
  keep?: (r: ExperimentRow) => boolean;
}) {
  const { group, aggregateInUrl, collapsed, keep } = grouping;
  const grouped = group !== null && group !== NO_GROUP;
  const flat = useLeaderboardRows(ws, app, filter, group === NO_GROUP);
  const groups = useGroupedRows(ws, app, filter, grouped ? group : null, aggregateInUrl ?? undefined);
  const data = groups.data;

  const items = useMemo<BoardItem[] | undefined>(() => {
    if (grouped) return data && groupItems(data, group, collapsed, groups.more, keep);
    return flat.rows && (keep ? flat.rows.filter(keep) : flat.rows);
  }, [grouped, data, group, collapsed, groups.more, keep, flat.rows]);

  if (!grouped) {
    const remaining = flat.total - (flat.rows?.length ?? 0);
    return {
      ...flat, items, grouped, loadGroup: groups.loadGroup,
      hasMore: remaining > 0, moreLabel: `Load more (${remaining} remaining)`,
    };
  }
  const remaining = data ? data.total_groups - data.groups.length : 0;
  return {
    rows: data?.rows, total: data ? Math.max(data.total, data.rows.length) : 0, items, grouped,
    queryError: groups.queryError, pageError: groups.pageError, moreError: groups.moreError,
    loadMore: groups.loadMore, loadGroup: groups.loadGroup, refresh: groups.refresh,
    visibleRef: flat.visibleRef, updatedAt: groups.updatedAt,
    hasMore: remaining > 0, moreLabel: `Load more (${plural(remaining, "group")} remaining)`,
  };
}
