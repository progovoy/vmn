import { Fragment } from "react";
import type { RunState } from "../types";
import { STATUS_ORDER } from "../util/filterTokens";
import { useRovingToolbar } from "../hooks/useRovingToolbar";
import ToggleChip from "./ToggleChip";
import "./FilterShortcuts.css";

/** The Outer runs failed chip's "≥ N% failed" option (plan 31 §1). */
export interface FailedShare {
  pct: number;
  on: boolean;
  onChange: (on: boolean) => void;
}

/** Status chips, the branch picker and the archived switch: shortcuts that
 *  write their clause into the query bar as a token. One toolbar, one Tab
 *  stop: the arrow keys move between them. With *failedShare*, the failed
 *  chip, once on, offers matching by failure share. */
export default function FilterShortcuts({
  statuses, onStatuses, branch, branches, onBranch, archived, onArchived, failedShare,
}: {
  failedShare?: FailedShare;
  statuses: readonly RunState[];
  onStatuses: (statuses: RunState[]) => void;
  branch: string;
  branches: readonly string[];
  onBranch: (branch: string) => void;
  archived: boolean;
  /** The archived switch appears with this callback. */
  onArchived?: (on: boolean) => void;
}) {
  const toggle = (s: RunState) =>
    onStatuses(STATUS_ORDER.filter((x) => (x === s ? !statuses.includes(s) : statuses.includes(x))));
  const roving = useRovingToolbar<HTMLDivElement>();
  return (
    <div className="filter-shortcuts" role="toolbar" aria-label="Filter shortcuts" {...roving}>
      <select
        role="combobox"
        aria-label="Branch"
        className="filter-control"
        value={branch}
        onChange={(e) => onBranch(e.target.value)}
        style={{ minWidth: 120 }}
      >
        <option value="">All branches</option>
        {branch && !branches.includes(branch) && <option value={branch}>{branch}</option>}
        {branches.map((b) => <option key={b} value={b}>{b}</option>)}
      </select>
      {STATUS_ORDER.map((s) => (
        <Fragment key={s}>
          <ToggleChip pressed={statuses.includes(s)} onChange={() => toggle(s)}>
            {s}
          </ToggleChip>
          {s === "failed" && failedShare && statuses.includes(s) && (
            <ToggleChip pressed={failedShare.on} title="outer runs with at least this share of failed runs" onChange={failedShare.onChange}>
              ≥ {failedShare.pct}% failed
            </ToggleChip>
          )}
        </Fragment>
      ))}
      {onArchived && (
        <ToggleChip className="archived-toggle" pressed={archived} title="include archived runs" onChange={onArchived}>
          archived
        </ToggleChip>
      )}
    </div>
  );
}
