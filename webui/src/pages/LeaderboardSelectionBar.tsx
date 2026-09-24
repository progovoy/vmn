import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ConfirmDialog from "../components/ConfirmDialog";
import { SELECT_ALL_CAP, type ArchiveVerb } from "../hooks/useBoardSelection";
import { MAX_COMPARE_RUNS } from "./compareRunsData";

const plural = (n: number) => `${n} run${n === 1 ? "" : "s"}`;
const selParams = (verstrs: string[]) => verstrs.map((v) => `sel=${encodeURIComponent(v)}`).join("&");

/** What can be done with the selected runs: count/clear, select everything
 *  filtered, compare, overlay, and archive/unarchive (after a confirm). */
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
  const go = (path: string) => navigate(`${base}/${path}`);
  const verb = (v: ArchiveVerb) => (v === "archive" ? "Archive" : "Unarchive");

  return (
    <>
      {total > 0 && (
        <button onClick={onSelectAll} title={`select every matching run (at most ${SELECT_ALL_CAP})`}>
          Select all {Math.min(total, SELECT_ALL_CAP)}
        </button>
      )}
      {n > 0 && (
        <span className="sel-count">
          {n} selected
          <button className="link" aria-label="Clear selection" onClick={onClear}>✕</button>
        </span>
      )}
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
      {n > 0 && (
        <>
          <button disabled={archiving} onClick={() => setConfirming("archive")}>Archive</button>
          {showUnarchive && (
            <button disabled={archiving} onClick={() => setConfirming("unarchive")}>Unarchive</button>
          )}
        </>
      )}
      {archiveError && <span className="error">{archiveError}</span>}
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
