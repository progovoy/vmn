import LiveStatus from "../components/LiveStatus";
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
 *  how fresh the rows are (Pause/Resume while live, else Refresh). */
export default function BoardCaption({ sortLabel, reversed, live }: {
  sortLabel: string | null; reversed: boolean; live: LiveProps;
}) {
  return (
    <div className="board-caption" id={BOARD_CAPTION_ID}>
      <span className="legend-chip"><span className="sq" aria-hidden="true" /> best in column</span>
      {sortLabel && (
        <span className="board-caption-sort">
          sorted by <b>{sortLabel}</b>, {reversed ? "worst first" : "best first"}
        </span>
      )}
      <span className="spacer" />
      <LiveStatus
        running={live.running} paused={live.paused} updatedAt={live.updatedAt}
        onPause={() => live.onPaused(true)} onResume={() => live.onPaused(false)}
        onRefresh={live.onRefresh}
      />
    </div>
  );
}
