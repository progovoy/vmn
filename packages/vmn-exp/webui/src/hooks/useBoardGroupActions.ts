/** A grouped board's wiring (plan 22): what the table's group headers do
 *  (fold, `+N more`, their checkbox) and the groups the charts colour by. */
import { useMemo } from "react";
import type { GroupAggregate } from "../apiGroups";
import type { GroupActions } from "../pages/LeaderboardTable";
import type { BoardGroup } from "../util/groupItems";
import type { HeaderCheck } from "./useBoardSelection";

export function useBoardGroupActions(
  data: { grouped: boolean; groups?: BoardGroup[]; loadGroup: (key: string) => void },
  grouping: { group: string | null | undefined; aggregate: GroupAggregate },
  onFold: (key: string) => void,
  selection: { checkOf: (v: readonly string[]) => HeaderCheck; toggleRows: (v: readonly string[]) => void },
) {
  const field = data.grouped ? grouping.group : undefined;
  const groupActions: GroupActions | undefined = field ? {
    field, aggregate: grouping.aggregate, onFold, onMore: data.loadGroup,
    checkOf: selection.checkOf, onCheck: selection.toggleRows,
  } : undefined;
  const groups = data.grouped ? data.groups : undefined;
  const chartGrouping = useMemo(
    () => (groups && field ? { field, groups } : undefined), [groups, field],
  );
  return { groupActions, chartGrouping };
}
