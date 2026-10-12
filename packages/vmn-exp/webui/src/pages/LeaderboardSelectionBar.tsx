import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ConfirmDialog from "../components/ConfirmDialog";
import { SELECT_ALL_CAP, type ArchiveVerb } from "../hooks/useBoardSelection";
import { useEscapeKey } from "../hooks/useEscapeKey";
import { useOffsetHeight } from "../hooks/useOffsetHeight";
import { MAX_COMPARE_RUNS } from "./compareRunsData";

const plural = (n: number) => `${n} run${n === 1 ? "" : "s"}`;
const selParams = (verstrs: string[]) => verstrs.map((v) => `sel=${encodeURIComponent(v)}`).join("&");
/** Room under the last rows beyond the bar itself: its 24px bottom offset and a 12px gap. */
const BAR_ROOM_PX = 36;

/** The bar floating at the bottom centre while runs are selected (Monday.com
 *  style): the count, what can be done with the runs — diff, compare,
 *  overlay, archive/unarchive (after a confirm), select every match — and a
 *  ✕ that clears the selection, as Escape does. */
export default function LeaderboardSelectionBar({
  selected, total, base, showUnarchive, archiving, archiveError,
  onClear, onSelectAll, onArchive,
}: {
  selected: string[];
  total: number;
  base: string;
  showUnarchive: boolean;
  archiving: boolean;
  archiveError: string | null;
  onClear: () => void;
  onSelectAll: () => void;
  onArchive: (verb: ArchiveVerb) => void;
}) {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState<ArchiveVerb | null>(null);
  const n = selected.length;
  const barRef = useRef<HTMLDivElement>(null);
  const barHeight = useOffsetHeight(barRef, n > 0);
  useEscapeKey(n > 0, onClear);
  if (n === 0) return null;

  const go = (path: string) => navigate(`${base}/${path}`);
  const verb = (v: ArchiveVerb) => (v === "archive" ? "Archive" : "Unarchive");
  const matching = Math.min(total, SELECT_ALL_CAP);

  return (
    <>
      {/* Room under the last rows, so the bar never covers them, wrapped or not. */}
      <div
        className="sel-bar-spacer" aria-hidden
        style={barHeight === null ? undefined : { height: barHeight + BAR_ROOM_PX }}
      />
      <div ref={barRef} className="sel-bar" role="region" aria-label="Selection">
        <span className="sel-badge" aria-hidden>{n}</span>
        <span className="sel-label" aria-hidden>{n === 1 ? "run" : "runs"} selected</span>
        <span className="sr-only" role="status">{n} selected</span>
        <span className="sel-actions">
          {n === 2 && (
            <button className="primary" onClick={() => go(
              `compare?v=${encodeURIComponent(selected[0])}&to=${encodeURIComponent(selected[1])}`,
            )}>
              Code diff of 2 selected →
            </button>
          )}
          {n >= 2 && n <= MAX_COMPARE_RUNS && (
            <button onClick={() => go(`compare-runs?${selParams(selected)}`)}>
              Compare {n} in a table →
            </button>
          )}
          {n >= 2 && (
            <button className="primary" onClick={() => go(`overlay?runs=${selected.map(encodeURIComponent).join(",")}`)}>
              Overlay curves →
            </button>
          )}
          <button disabled={archiving} onClick={() => setConfirming("archive")}>Archive</button>
          {showUnarchive && (
            <button disabled={archiving} onClick={() => setConfirming("unarchive")}>Unarchive</button>
          )}
          {n < matching && (
            <button onClick={onSelectAll} title={`select every matching run (at most ${SELECT_ALL_CAP})`}>
              Select all {matching} matching
            </button>
          )}
          {archiveError && <span className="error">{archiveError}</span>}
        </span>
        <button className="sel-close" aria-label="Clear selection" title="Clear selection (Esc)" onClick={onClear}>
          ✕
        </button>
      </div>
      {confirming && (
        <ConfirmDialog
          message={`${verb(confirming)} ${plural(Math.min(n, SELECT_ALL_CAP))}?`}
          onCancel={() => setConfirming(null)}
          onConfirm={() => { onArchive(confirming); setConfirming(null); }}
        />
      )}
    </>
  );
}
