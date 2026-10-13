import type { ReactNode } from "react";
import LiveStatus from "../components/LiveStatus";
import { isGroupCountId } from "../util/groupCountSort";
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
export default function BoardCaption({ sortLabel, reversed, live, tools, legend = true }: {
  sortLabel: string | null; reversed: boolean; live: LiveProps; tools?: ReactNode;
  /** The "best in column" chip; the Jobs view has no best-in-column cells. */
  legend?: boolean;
}) {
  return (
    <div className="board-caption">
      <div className="board-caption-desc" id={BOARD_CAPTION_ID}>
        {legend && <span className="legend-chip"><span className="sq" aria-hidden="true" /> best in column</span>}
        {sortLabel && (
          <span className="board-caption-sort">
            {isGroupCountId(sortLabel)
              ? <>groups sorted by <b>{sortLabel.slice(2)} runs</b>, {reversed ? "fewest first" : "most first"}</>
              : <>sorted by <b>{sortLabel}</b>, {reversed ? "worst first" : "best first"}</>}
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
