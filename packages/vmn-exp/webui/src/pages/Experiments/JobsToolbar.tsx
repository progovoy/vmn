/** The Jobs view's actions in the page head (Jobs | Single runs is the
 *  page's view switch, §3.1): New run (where a run can be created), saved
 *  views and Group by over the jobs (plan 23 §3.4: fields from the facets;
 *  "parent run" is left out, a job has none). */
import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import GroupByMenu from "../../components/GroupByMenu";
import SavedViews from "../../components/SavedViews";
import type { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { useCanCreateRun } from "../../shell/useAppExists";
import { LINK_GROUPS, NO_GROUP, groupFields } from "../../util/groupBy";
import { groupSortOf } from "../../util/groupCountSort";
import type { useJobsBoard } from "./useJobsBoard";
import "../leaderboardToolbar.css";

const JOB_LINKS = LINK_GROUPS.filter((l) => l.value !== "parent");

export default function JobsToolbar({ ws, app, view, board, onViewApplied }: {
  ws: string; app: string;
  /** A saved view replaced the URL: controls holding their own state reset. */
  onViewApplied: () => void;
  view: ReturnType<typeof useLeaderboardView>;
  board: ReturnType<typeof useJobsBoard>;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const canCreate = useCanCreateRun(ws, app);
  const { data } = board;
  const fields = useMemo(() => groupFields(board.facets), [board.facets]);
  return (
    <div className="toolbar board-actions">
      {canCreate && !view.creating && (
        <button className="primary" onClick={() => view.openCreate(true)}>New run</button>
      )}
      <SavedViews
        ws={ws} app={app} search={location.search}
        onApply={(search) => { navigate({ search }, { replace: true }); onViewApplied(); }}
      />
      <GroupByMenu
        value={board.group} links={JOB_LINKS} fields={fields}
        onChange={(g) => view.setGroup(g, NO_GROUP)}
        aggregate={view.aggParam ?? data.aggregate ?? data.defaultAggregate ?? "mean"}
        onAggregate={(a) => view.setAggregate(a, data.defaultAggregate)}
        groupSort={groupSortOf(view.sort)} onGroupSort={view.setGroupSort}
      />
    </div>
  );
}
