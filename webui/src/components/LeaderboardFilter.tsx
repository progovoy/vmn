import { useEffect, useMemo, useState } from "react";
import type { ExperimentRow, RunState } from "../types";
import { useDebounce } from "../hooks/useDebounce";

/** Display order of the status toggles (only those present are shown). */
const STATUS_ORDER: RunState[] = [
  "running", "stuck", "failed", "succeeded", "created",
];

export default function LeaderboardFilter({ rows, onFilter, onStatusChange }: {
  rows: ExperimentRow[];
  onFilter: (filtered: ExperimentRow[]) => void;
  /** Picked statuses as the `?status=` CSV the list endpoint takes. */
  onStatusChange?: (csv: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [branch, setBranch] = useState("");
  const [statuses, setStatuses] = useState<RunState[]>([]);
  const debouncedSearch = useDebounce(search);

  const branches = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => { if (r.branch) set.add(r.branch); });
    return [...set].sort();
  }, [rows]);

  const knownStatuses = useMemo(() => {
    const set = new Set(rows.map((r) => r.status));
    return STATUS_ORDER.filter((s) => set.has(s));
  }, [rows]);

  const toggleStatus = (s: RunState) =>
    setStatuses((cur) => {
      const next = cur.includes(s)
        ? cur.filter((x) => x !== s)
        : STATUS_ORDER.filter((x) => x === s || cur.includes(x));
      onStatusChange?.(next.join(","));
      return next;
    });

  useEffect(() => {
    let filtered = rows;
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase();
      filtered = filtered.filter((r) =>
        (r.note ?? "").toLowerCase().includes(q) ||
        r.verstr.toLowerCase().includes(q) ||
        (r.branch ?? "").toLowerCase().includes(q)
      );
    }
    if (branch) {
      filtered = filtered.filter((r) => r.branch === branch);
    }
    if (statuses.length) {
      filtered = filtered.filter((r) => r.status && statuses.includes(r.status));
    }
    onFilter(filtered);
  }, [rows, debouncedSearch, branch, statuses, onFilter]);

  const clear = () => {
    setSearch("");
    setBranch("");
    setStatuses([]);
    onStatusChange?.("");
  };

  const hasFilter = search || branch || statuses.length > 0;

  return (
    <div className="toolbar" style={{ gap: 8, marginBottom: 0 }}>
      <input
        type="text"
        placeholder="Search note, verstr, branch..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ flex: 1, minWidth: 160, maxWidth: 300 }}
      />
      <select
        role="combobox"
        value={branch}
        onChange={(e) => setBranch(e.target.value)}
        style={{ minWidth: 120 }}
      >
        <option value="">All branches</option>
        {branches.map((b) => (
          <option key={b} value={b}>{b}</option>
        ))}
      </select>
      {knownStatuses.map((s) => (
        <button
          key={s}
          className="status-toggle"
          aria-pressed={statuses.includes(s)}
          onClick={() => toggleStatus(s)}
        >
          {s}
        </button>
      ))}
      {hasFilter && (
        <button title="Clear filters" onClick={clear} style={{ padding: "4px 10px" }}>
          ✕
        </button>
      )}
    </div>
  );
}
