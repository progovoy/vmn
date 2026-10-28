/** The Jobs view's actions in the page head (Jobs | Single runs is the
 *  page's view switch, §3.1): New run (where a run can be created), saved
 *  views and Group by over the jobs (plan 23 §3.4: fields from the facets).
 *  Ungrouped, the view is grouped by parent run, so the menu checks that;
 *  "none" opens All runs flat. */
import { useMemo } from "react";
import GroupByMenu from "../../components/GroupByMenu";
import BoardViews from "../../components/BoardViews";
import type { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { useCanCreateRun } from "../../shell/useAppExists";
import { LINK_GROUPS, NO_GROUP, groupFields } from "../../util/groupBy";
import { groupSortOf } from "../../util/groupCountSort";
import type { useJobsBoard } from "./useJobsBoard";
import "../leaderboardToolbar.css";

const PARENT = "parent";
const JOB_LINKS = LINK_GROUPS.map((l) => (l.value === PARENT ? { ...l, label: `${l.label} (this view)` } : l));

export default function JobsToolbar({ ws, app, view, board, onViewApplied, onAll }: {
  ws: string; app: string;
  /** Open All runs (Group by none). */
  onAll: () => void;
  /** A saved view replaced the URL: controls holding their own state reset. */
  onViewApplied: () => void;
  view: ReturnType<typeof useLeaderboardView>;
  board: ReturnType<typeof useJobsBoard>;
}) {
  const canCreate = useCanCreateRun(ws, app);
  const { data } = board;
  const fields = useMemo(() => groupFields(board.facets), [board.facets]);
  return (
    <div className="toolbar board-actions">
      {canCreate && !view.creating && (
        <button className="primary" onClick={() => view.openCreate(true)}>New run</button>
      )}
      <BoardViews ws={ws} app={app} page="jobs" onViewApplied={onViewApplied} />
      <GroupByMenu
        value={board.group} viewGroup={PARENT} links={JOB_LINKS} fields={fields}
        onChange={(g) => (g === NO_GROUP ? onAll() : view.setGroup(g === PARENT ? NO_GROUP : g, NO_GROUP))}
        aggregate={view.aggParam ?? data.aggregate ?? data.defaultAggregate ?? "mean"}
        onAggregate={(a) => view.setAggregate(a, data.defaultAggregate)}
        groupSort={groupSortOf(view.sort)} onGroupSort={view.setGroupSort}
      />
    </div>
  );
}
