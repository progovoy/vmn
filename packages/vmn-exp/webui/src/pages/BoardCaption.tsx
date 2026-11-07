import type { ReactNode } from "react";
import LiveStatus from "../components/LiveStatus";
import type { Goal } from "../util";
import { isGroupCountId } from "../util/groupCountSort";
import { IDX_SORT } from "./LeaderboardHead";
import "./boardCaption.css";

export const BOARD_CAPTION_ID = "board-caption";

export interface LiveProps {
  running: boolean;
  paused: boolean;
  updatedAt: number;
  onPaused: (paused: boolean) => void;
  onRefresh: () => unknown;
}

/** Under the board, describing it: the "best in column" legend, the sort and
 *  how fresh the rows are (Pause/Resume while live, else Refresh); then
 *  *tools*, which are not part of the description. */
export default function BoardCaption({ sortLabel, reversed, order, goal, live, tools, legend = true }: {
  sortLabel: string | null; reversed: boolean; live: LiveProps; tools?: ReactNode;
  /** The sort's direction and its metric's goal (null: a metric without one). */
  order?: "asc" | "desc" | null; goal?: Goal;
  /** The "best in column" chip; the Jobs view has no best-in-column cells. */
  legend?: boolean;
}) {
  return (
    <div className="board-caption">
      <div className="board-caption-desc" id={BOARD_CAPTION_ID}>
        {legend && <span className="legend-chip"><span className="sq" aria-hidden="true" /> best in column</span>}
        {sortLabel && (
          <span className="board-caption-sort">
            {sortLabel === IDX_SORT ? (reversed ? "oldest first" : "newest first")
              : isGroupCountId(sortLabel)
                ? <>groups sorted by <b>{sortLabel.slice(2)} runs</b>, {reversed ? "fewest first" : "most first"}</>
                : <>sorted by <b>{sortLabel}</b>, {metricOrderText(reversed, order, goal)}</>}
          </span>
        )}
        <span className="spacer" />
        <LiveStatus
          running={live.running} paused={live.paused} updatedAt={live.updatedAt}
          onPause={() => live.onPaused(true)} onResume={() => live.onPaused(false)}
          onRefresh={live.onRefresh}
        />
      </div>
      {tools}
    </div>
  );
}

/** Best/worst first toward a goal; without one, which end comes first. */
const metricOrderText = (reversed: boolean, order: "asc" | "desc" | null | undefined, goal: Goal | undefined) =>
  goal === null ? `${order === "desc" ? "high" : "low"} first (no goal)` : reversed ? "worst first" : "best first";
