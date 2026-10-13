import type { RunState } from "../types";
import { STATUS_ORDER } from "../util/filterTokens";
import { useRovingToolbar } from "../hooks/useRovingToolbar";
import "./FilterShortcuts.css";

/** Status chips, the branch picker and the archived switch: shortcuts that
 *  write their clause into the query bar as a token. One toolbar, one Tab
 *  stop: the arrow keys move between them. */
export default function FilterShortcuts({
  statuses, onStatuses, branch, branches, onBranch, archived, onArchived,
}: {
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
        <button
          key={s}
          type="button"
          className="status-toggle"
          aria-pressed={statuses.includes(s)}
          onClick={() => toggle(s)}
        >
          {s}
        </button>
      ))}
      {onArchived && (
        <button
          type="button"
          className="status-toggle archived-toggle"
          aria-pressed={archived}
          title="include archived runs"
          onClick={() => onArchived(!archived)}
        >
          archived
        </button>
      )}
    </div>
  );
}
