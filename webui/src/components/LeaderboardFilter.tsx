import { useEffect, useMemo, useState } from "react";
import type { ExperimentRow } from "../types";
import { useDebounce } from "../hooks/useDebounce";

export default function LeaderboardFilter({ rows, onFilter }: {
  rows: ExperimentRow[];
  onFilter: (filtered: ExperimentRow[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [branch, setBranch] = useState("");
  const debouncedSearch = useDebounce(search);

  const branches = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => { if (r.branch) set.add(r.branch); });
    return [...set].sort();
  }, [rows]);

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
    onFilter(filtered);
  }, [rows, debouncedSearch, branch, onFilter]);

  const clear = () => {
    setSearch("");
    setBranch("");
  };

  const hasFilter = search || branch;

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
      {hasFilter && (
        <button title="Clear filters" onClick={clear} style={{ padding: "4px 10px" }}>
          ✕
        </button>
      )}
    </div>
  );
}
