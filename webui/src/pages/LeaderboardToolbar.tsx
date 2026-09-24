import { useLocation, useNavigate } from "react-router-dom";
import ColumnPicker from "../components/ColumnPicker";
import LiveToggle from "../components/LiveToggle";
import SavedViews from "../components/SavedViews";
import type { useLeaderboardColumns } from "../hooks/useLeaderboardColumns";
import type { useLeaderboardView } from "../hooks/useLeaderboardView";
import type { useBoardSelection } from "../hooks/useBoardSelection";
import LeaderboardSelectionBar from "./LeaderboardSelectionBar";

/** The bar above the leaderboard: live toggle, selection actions, saved
 *  views, the create button and the column picker. */
export default function LeaderboardToolbar({
  ws, app, base, view, cols, selection, total, live, onLive, onViewApplied,
}: {
  ws: string;
  app: string;
  base: string;
  view: ReturnType<typeof useLeaderboardView>;
  cols: ReturnType<typeof useLeaderboardColumns>;
  selection: ReturnType<typeof useBoardSelection>;
  total: number;
  live: boolean;
  onLive: () => void;
  /** A saved view replaced the URL: controls holding their own state reset. */
  onViewApplied: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div className="toolbar">
      <span className="legend-chip"><span className="sq" /> best in column</span>
      <LiveToggle live={live} onToggle={onLive} />
      <span className="spacer" />
      <LeaderboardSelectionBar
        selected={[...view.selected]}
        total={total}
        base={base}
        showUnarchive={view.archived}
        archiving={selection.archiving}
        archiveError={selection.archiveError}
        onClear={() => view.setSelected([])}
        onSelectAll={selection.selectAll}
        onArchive={selection.archive}
      />
      {!view.creating && <button onClick={() => view.openCreate(true)}>+ New experiment</button>}
      <SavedViews
        ws={ws} app={app} search={location.search}
        onApply={(search) => { navigate({ search }, { replace: true }); onViewApplied(); }}
      />
      <ColumnPicker
        columns={cols.paramCols} visible={cols.visibleParams}
        onToggle={(c) => view.toggleHidden(`p:${c}`)}
        metricColumns={cols.metricCols} visibleMetrics={cols.visibleMetrics}
        onToggleMetric={(c) => view.toggleHidden(`m:${c}`)}
        otherColumns={cols.otherCols} visibleOther={cols.visibleOther}
        onToggleOther={(c) => view.toggleHidden(`c:${c}`)}
      />
    </div>
  );
}
