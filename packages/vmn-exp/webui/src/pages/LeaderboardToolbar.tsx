import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ColumnPicker from "../components/ColumnPicker";
import LiveStatus from "../components/LiveStatus";
import SavedViews from "../components/SavedViews";
import { useCanCreateRun } from "../shell/useAppExists";
import { hideColumn } from "../hooks/useColumnEdits";
import type { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import type { useLeaderboardView } from "../hooks/useLeaderboardView";
import "./leaderboardToolbar.css";

/** The bar above the leaderboard: live status, the create button (only where
 *  a run can be created), saved views and the columns (the selection's
 *  actions float at the bottom). */
export default function LeaderboardToolbar({
  ws, app, view, cols, live, onViewApplied, onResetColumns,
}: {
  ws: string;
  app: string;
  view: ReturnType<typeof useLeaderboardView>;
  cols: ReturnType<typeof useLeaderboardColumns>;
  live: {
    running: boolean;
    paused: boolean;
    updatedAt: number;
    onPaused: (paused: boolean) => void;
    onRefresh: () => unknown;
  };
  /** A saved view replaced the URL: controls holding their own state reset. */
  onViewApplied: () => void;
  /** Drop the dragged widths and column order; omitted while there are none. */
  onResetColumns?: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const canCreate = useCanCreateRun(ws, app);
  const onMoveColumn = useCallback(
    (key: string, delta: number) => view.moveColumn(key, delta, cols.defaultKeys, cols.pinned),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view.moveColumn, cols.defaultKeys, cols.pinned],
  );
  return (
    <div className="toolbar">
      <span className="legend-chip"><span className="sq" /> best in column</span>
      <LiveStatus
        running={live.running} paused={live.paused} updatedAt={live.updatedAt}
        onPause={() => live.onPaused(true)} onResume={() => live.onPaused(false)}
        onRefresh={live.onRefresh}
      />
      <span className="spacer" />
      {canCreate && !view.creating && <button onClick={() => view.openCreate(true)}>New run</button>}
      <SavedViews
        ws={ws} app={app} search={location.search}
        onApply={(search) => { navigate({ search }, { replace: true }); onViewApplied(); }}
      />
      {onResetColumns && (
        <button onClick={onResetColumns} title="restore the default column widths and order">
          Reset columns
        </button>
      )}
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
        orderedCells={cols.cells}
        pinnedCols={cols.pinned}
        onMoveColumn={onMoveColumn}
        onTogglePin={(key) => view.togglePin(key, cols.pinned, cols.defaultPins)}
      />
    </div>
  );
}
