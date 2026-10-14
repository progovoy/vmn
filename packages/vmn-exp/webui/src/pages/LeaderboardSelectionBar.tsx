import { type ReactNode, type RefObject, useId, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ConfirmDialog from "../components/ConfirmDialog";
import type { ArchiveVerb } from "../hooks/useArchiveJob";
import { useEscapeKey } from "../hooks/useEscapeKey";
import { useOffsetHeight } from "../hooks/useOffsetHeight";
import { fmtCount, plural } from "../util";
import { SELECT_ALL_CAP, type RunPick } from "../util/runSelection";
import { COMPARE_PER_GROUP, compareList, summarizeSelection, type QueryGroup } from "../util/selectionGroups";
import { compareSearch } from "./Compare/selection";
import SelectionPicks from "./SelectionPicks";
import "./selectionBar.css";

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
function BarAction({ label, reason, title, primary, onClick }: {
  label: ReactNode; reason: string | null; title?: string; primary?: boolean; onClick: () => void;
}) {
  const id = useId();
  const off = reason !== null;
  return (
    <>
      <button
        className={primary && !off ? "primary" : undefined}
        aria-disabled={off || undefined} title={reason ?? title}
        aria-describedby={off ? id : undefined} onClick={off ? undefined : onClick}
      >
        {label}
      </button>
      {off && <span id={id} className="sr-only">{reason}</span>}
    </>
  );
}

/** The bar floating at the bottom centre while runs are selected (Monday.com
 *  style), the app-wide tray: the count and its jobs (expandable to the
 *  picks by job, each removable), what can be done with the runs — one Compare (N) to the
 *  Compare page, archive/unarchive (after a confirm), select every match — and a
 *  ✕ that clears the selection, as Escape does. Its actions and slots are
 *  the same at every count, so it never changes size as runs are picked. */
export default function LeaderboardSelectionBar({
  selected, total, base, showUnarchive, archiving, archiveError,
  onClear, onSelectAll, onArchive, matching = null, onPreview, uncapped = false,
  picks, groups = [], onRemove, onRemoveGroup, escClears = true, overlap = 0, approximate = false, tagAction,
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
  /** The board's query is selected as a group (plan 23 S4): how many it matched. */
  matching?: number | null;
  /** Counts what an archive by query acts on, for its confirm. */
  onPreview?: (verb: ArchiveVerb) => Promise<number>;
  /** "Select all" selects the query itself: no cap. */
  uncapped?: boolean;
  /** The tray's picks (their jobs): with *onRemove*, the bar expands to list them. */
  picks?: readonly RunPick[];
  onRemove?: (verstr: string) => void;
  /** The selected queries (a job's "Select all N matching"), each counted and removable. */
  groups?: readonly QueryGroup[];
  onRemoveGroup?: (group: QueryGroup) => void;
  /** Escape clears the selection (a board's page; not a page without a board). */
  escClears?: boolean;
  /** Explicit picks a group also matches: counted once. */
  overlap?: number;
  /** Not every such pick is known yet: the count is an upper bound. */
  approximate?: boolean;
  /** The Tag action, next to Archive. */
  tagAction?: ReactNode;
}) {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState<{ verb: ArchiveVerb; count: number } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const n = selected.length + groups.reduce((sum, g) => sum + g.count, 0) - overlap;
  const atMost = approximate ? "≤" : "";
  const jobs = picks ? summarizeSelection(picks, groups).jobs : 0;
  const compared = compareList(selected.map((verstr) => ({ verstr })), groups);
  const fromJobs = jobs ? ` from ${plural(jobs, "outer run")}` : "";
  const barRef = useRef<HTMLDivElement>(null);
  const allRef = useRef<HTMLButtonElement>(null);
  const barHeight = useOffsetHeight(barRef, n > 0);
  const selectable = uncapped ? total : Math.min(total, SELECT_ALL_CAP);
  const canSelectAll = matching === null && (uncapped ? selectable > 0 : n < selectable);
  useKeepFocusInBar(barRef, allRef, canSelectAll);
  useEscapeKey(n > 0 && escClears, onClear);
  if (n === 0) return null;

  const go = (path: string) => navigate(`${base}/${path}`);
  const verb = (v: ArchiveVerb) => (v === "archive" ? "Archive" : "Unarchive");
  // By query, the server counts the runs first (`dry_run`).
  const ask = (v: ArchiveVerb) => {
    setPreviewError(null);
    if (!onPreview) {
      setConfirming({ verb: v, count: Math.min(n, SELECT_ALL_CAP) });
      return;
    }
    onPreview(v).then(
      (count) => setConfirming({ verb: v, count }),
      (e) => setPreviewError(`Could not count the runs: ${String((e as Error).message ?? e)}`),
    );
  };

  return (
    <>
      {/* Room under the last rows, so the bar never covers them, wrapped or not. */}
      <div
        className="sel-bar-spacer" aria-hidden
        style={barHeight === null ? undefined : { height: barHeight + BAR_ROOM_PX }}
      />
      <div className="sel-dock">
        <div className="sel-toast" role="alert">{previewError ?? archiveError}</div>
        {expanded && picks && onRemove && (
          <SelectionPicks
            id={listId} picks={picks} groups={groups} base={base} onRemove={onRemove} onRemoveGroup={onRemoveGroup}
          />
        )}
        <div ref={barRef} className="sel-bar" role="region" aria-label="Selection">
          <span key={n} className="sel-badge" aria-hidden>{atMost}{fmtCount(n)}</span>
          <span className="sel-label">
            <span className="sel-label-text" aria-hidden data-widest="runs selected">
              {n === 1 ? "run" : "runs"} selected
            </span>
            {picks && onRemove && (
              <button
                className="link sel-expand" aria-expanded={expanded} aria-controls={expanded ? listId : undefined}
                title={expanded ? "Hide the selected runs" : "List the selected runs by outer run"}
                onClick={() => setExpanded((e) => !e)}
              >
                {jobs ? fromJobs.trim() : "list runs"} {expanded ? "▴" : "▾"}
              </button>
            )}
            <span
              className="sel-all" aria-hidden={canSelectAll ? undefined : true}
              style={canSelectAll ? undefined : { visibility: "hidden" }}
            >
              <button
                ref={allRef} className="link" tabIndex={canSelectAll ? undefined : -1} onClick={onSelectAll}
                title={uncapped ? "select every matching run" : `select every matching run (at most ${SELECT_ALL_CAP})`}
              >
                Select all {fmtCount(selectable)} matching
              </button>
            </span>
          </span>
          <span className="sr-only" role="status">{approximate && "at most "}{fmtCount(n)} selected{fromJobs}</span>
          <span className="sel-actions">
            <BarAction
              label={<>Compare <span className="sel-count">({compared.length})</span></>}
              primary reason={compareReason(compared.length)}
              title={groups.length ? `Compares the picked runs and the top ${COMPARE_PER_GROUP} runs of each selected query` : undefined}
              onClick={() => go(`compare-runs?${compareSearch("curves", compared)}`)}
            />
            <button disabled={archiving} onClick={() => ask("archive")}>Archive</button>
            {tagAction}
            {showUnarchive && (
              <button disabled={archiving} onClick={() => ask("unarchive")}>Unarchive</button>
            )}
          </span>
          <button className="sel-close" aria-label="Clear selection" title="Clear selection (Esc)" onClick={onClear}>
            ✕
          </button>
        </div>
      </div>
      {confirming && (
        <ConfirmDialog
          message={`${verb(confirming.verb)} ${plural(confirming.count, "run")}?`}
          onCancel={() => setConfirming(null)}
          onConfirm={() => { onArchive(confirming.verb); setConfirming(null); }}
        />
      )}
    </>
  );
}
