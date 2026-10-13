import { type ReactNode, type RefObject, useId, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ConfirmDialog from "../components/ConfirmDialog";
import { SELECT_ALL_CAP, type ArchiveVerb } from "../hooks/useBoardSelection";
import { useEscapeKey } from "../hooks/useEscapeKey";
import { useOffsetHeight } from "../hooks/useOffsetHeight";
import { compareSearch } from "./Compare/selection";
import "./selectionBar.css";

const plural = (n: number) => `${n} run${n === 1 ? "" : "s"}`;
/** Room under the last rows beyond the bar itself: its 24px bottom offset and a 12px gap. */
const BAR_ROOM_PX = 36;

/** Why Compare can't run on *n* selected runs, or null when it can. Each
 *  Compare tab caps the runs it shows itself, so there is no upper bound. */
const compareReason = (n: number) => (n >= 2 ? null : "Select 2 or more runs");

/** Hiding a focused select-all (every match now picked) would drop focus to
 *  the page; hand it to the bar's first enabled action instead. */
function useKeepFocusInBar(barRef: RefObject<HTMLDivElement | null>,
  allRef: RefObject<HTMLButtonElement | null>, canSelectAll: boolean) {
  useLayoutEffect(() => {
    if (canSelectAll || document.activeElement !== allRef.current) return;
    barRef.current?.querySelector<HTMLButtonElement>(
      '.sel-actions button:not(:disabled):not([aria-disabled="true"]), .sel-close',
    )?.focus();
  }, [barRef, allRef, canSelectAll]);
}

/** An action that stays in place at every count. When the selection doesn't
 *  fit it, it is aria-disabled rather than disabled: still a Tab stop that
 *  announces its reason (tooltip and description), but inert. */
function BarAction({ label, reason, primary, onClick }: {
  label: ReactNode; reason: string | null; primary?: boolean; onClick: () => void;
}) {
  const id = useId();
  const off = reason !== null;
  return (
    <>
      <button
        className={primary && !off ? "primary" : undefined}
        aria-disabled={off || undefined} title={reason ?? undefined}
        aria-describedby={off ? id : undefined} onClick={off ? undefined : onClick}
      >
        {label}
      </button>
      {off && <span id={id} className="sr-only">{reason}</span>}
    </>
  );
}

/** The bar floating at the bottom centre while runs are selected (Monday.com
 *  style): the count, what can be done with the runs — one Compare (N) to the
 *  Compare page, archive/unarchive (after a confirm), select every match — and a
 *  ✕ that clears the selection, as Escape does. Its actions and slots are
 *  the same at every count, so it never changes size as runs are picked. */
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
  const allRef = useRef<HTMLButtonElement>(null);
  const barHeight = useOffsetHeight(barRef, n > 0);
  const matching = Math.min(total, SELECT_ALL_CAP);
  const canSelectAll = n < matching;
  useKeepFocusInBar(barRef, allRef, canSelectAll);
  useEscapeKey(n > 0, onClear);
  if (n === 0) return null;

  const go = (path: string) => navigate(`${base}/${path}`);
  const verb = (v: ArchiveVerb) => (v === "archive" ? "Archive" : "Unarchive");

  return (
    <>
      {/* Room under the last rows, so the bar never covers them, wrapped or not. */}
      <div
        className="sel-bar-spacer" aria-hidden
        style={barHeight === null ? undefined : { height: barHeight + BAR_ROOM_PX }}
      />
      <div className="sel-dock">
        <div className="sel-toast" role="alert">{archiveError}</div>
        <div ref={barRef} className="sel-bar" role="region" aria-label="Selection">
          <span key={n} className="sel-badge" aria-hidden>{n}</span>
          <span className="sel-label">
            <span className="sel-label-text" aria-hidden data-widest="runs selected">
              {n === 1 ? "run" : "runs"} selected
            </span>
            <span
              className="sel-all" aria-hidden={canSelectAll ? undefined : true}
              style={canSelectAll ? undefined : { visibility: "hidden" }}
            >
              <button
                ref={allRef} className="link" tabIndex={canSelectAll ? undefined : -1} onClick={onSelectAll}
                title={`select every matching run (at most ${SELECT_ALL_CAP})`}
              >
                Select all {matching} matching
              </button>
            </span>
          </span>
          <span className="sr-only" role="status">{n} selected</span>
          <span className="sel-actions">
            <BarAction
              label={<>Compare <span className="sel-count">({n})</span></>}
              primary reason={compareReason(n)}
              onClick={() => go(`compare-runs?${compareSearch("curves", selected)}`)}
            />
            <button disabled={archiving} onClick={() => setConfirming("archive")}>Archive</button>
            {showUnarchive && (
              <button disabled={archiving} onClick={() => setConfirming("unarchive")}>Unarchive</button>
            )}
          </span>
          <button className="sel-close" aria-label="Clear selection" title="Clear selection (Esc)" onClick={onClear}>
            ✕
          </button>
        </div>
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
