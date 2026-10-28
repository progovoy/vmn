import { useCallback } from "react";
import ColumnPicker from "../components/ColumnPicker";
import GroupByMenu from "../components/GroupByMenu";
import BoardViews from "../components/BoardViews";
import { useCanCreateRun } from "../shell/useAppExists";
import { hideColumn } from "../hooks/useColumnEdits";
import type { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import type { useLeaderboardView } from "../hooks/useLeaderboardView";
import type { BoardGrouping } from "../hooks/useBoardAggregate";
import { NO_GROUP } from "../util/groupBy";
import { groupSortOf } from "../util/groupCountSort";
import type { ViewPage } from "../util/teamViews";
import "./leaderboardToolbar.css";

/** The board's actions, in its page head: the create button (primary, only
 *  where a run can be created), saved views, Group by and the columns (the live status
 *  is the table's caption; the selection's actions float at the bottom). */
export default function LeaderboardToolbar({
  ws, app, view, cols, grouping, onViewApplied, onResetColumns, job, page,
}: {
  ws: string;
  app: string;
  view: ReturnType<typeof useLeaderboardView>;
  cols: ReturnType<typeof useLeaderboardColumns>;
  grouping: BoardGrouping;
  /** A saved view replaced the URL: controls holding their own state reset. */
  onViewApplied: () => void;
  /** Drop the dragged widths and column order; omitted while there are none. */
  onResetColumns?: () => void;
  /** A job's Runs tab (its verstr): no New run, and saved views of its own. */
  job?: string;
  /** Whose team views it lists (plan 28 P4); default an outer run's page with *job*, else All runs. */
  page?: ViewPage;
}) {
  const canCreate = useCanCreateRun(ws, app);
  const onMoveColumn = useCallback(
    (key: string, delta: number) => view.moveColumn(key, delta, cols.defaultKeys, cols.pinned),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view.moveColumn, cols.defaultKeys, cols.pinned],
  );
  return (
    <div className="toolbar board-actions">
      {canCreate && !job && !view.creating && (
        <button className="primary" onClick={() => view.openCreate(true)}>New run</button>
      )}
      <BoardViews ws={ws} app={app} page={page ?? (job ? "job" : "runs")} job={job} onViewApplied={onViewApplied} />
      {onResetColumns && (
        <button onClick={onResetColumns} title="restore the default column widths and order">
          Reset columns
        </button>
      )}
      <GroupByMenu
        value={grouping.group ?? NO_GROUP} links={grouping.links} fields={grouping.fields}
        onChange={grouping.setGroup}
        aggregate={grouping.aggregate} onAggregate={grouping.setAggregate}
        groupSort={groupSortOf(view.sort)} onGroupSort={view.setGroupSort}
      />
      <ColumnPicker
        columns={cols.paramCols} visible={cols.visibleParams}
        onToggle={(c) => view.setColumnShown(`p:${c}`, !cols.visibleParams.includes(c))}
        metricColumns={cols.metricCols} visibleMetrics={cols.visibleMetrics}
        onToggleMetric={(c) => {
          if (cols.visibleMetrics.includes(c)) hideColumn(view, cols.schemaHidden, `m:${c}`);
          else view.setColumnShown(`m:${c}`, true);
        }}
        otherColumns={cols.otherCols} visibleOther={cols.visibleOther}
        onToggleOther={(c) => {
          const id = `c:${c}`;
          // Comments flip their `hide=` key; the rest record the choice in show=/hide=.
          if (c === "comments") view.toggleHidden(id);
          else view.setColumnShown(id, !cols.visibleOther.includes(c));
        }}
        tagColumns={cols.tagCols} visibleTags={cols.visibleTags}
        onToggleTag={(k) => view.setColumnShown(`t:${k}`, !cols.visibleTags.includes(k))}
        orderedCells={cols.cells}
        pinnedCols={cols.pinned}
        onMoveColumn={onMoveColumn}
        onTogglePin={(key) => view.togglePin(key, cols.pinned, cols.defaultPins)}
      />
    </div>
  );
}
