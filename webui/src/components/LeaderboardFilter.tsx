import { useEffect, useMemo, useState } from "react";
import type { ExperimentRow, RunState } from "../types";
import { useDebounce } from "../hooks/useDebounce";

/** Every status, in display order. Static on purpose: the list endpoint answers
 *  the `?status=` filter, so the rows on hand no longer show what else exists. */
const STATUS_ORDER: RunState[] = [
  "running", "stuck", "failed", "succeeded", "created",
];

/** The syntax hint on the query box: a query that uses most of the language. */
const QUERY_EXAMPLE = 'metrics.loss < 0.5 and status = "succeeded"';

export default function LeaderboardFilter({
  rows, onFilter, onStatusChange, onQueryChange, queryError,
}: {
  rows: ExperimentRow[];
  onFilter: (filtered: ExperimentRow[]) => void;
  /** Picked statuses as the `?status=` CSV the list endpoint takes. */
  onStatusChange?: (csv: string) => void;
  /** The typed query as the `?q=` the list endpoint takes, debounced. */
  onQueryChange?: (query: string) => void;
  /** What the server said about the query it refused; shown beside the box. */
  queryError?: string | null;
}) {
  const [search, setSearch] = useState("");
  const [branch, setBranch] = useState("");
  const [statuses, setStatuses] = useState<RunState[]>([]);
  const [query, setQuery] = useState("");
  const debouncedSearch = useDebounce(search);
  // Long enough that a whole field name is typed before it costs a request.
  const debouncedQuery = useDebounce(query, 300);

  const branches = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => { if (r.branch) set.add(r.branch); });
    return [...set].sort();
  }, [rows]);

  const toggleStatus = (s: RunState) =>
    setStatuses((cur) =>
      cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]
    );

  useEffect(() => {
    onStatusChange?.(STATUS_ORDER.filter((s) => statuses.includes(s)).join(","));
  }, [statuses, onStatusChange]);

  useEffect(() => {
    onQueryChange?.(debouncedQuery.trim());
  }, [debouncedQuery, onQueryChange]);

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
    setStatuses([]);
    setQuery("");
  };

  const hasFilter = search || branch || query || statuses.length > 0;

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
      {STATUS_ORDER.map((s) => (
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
      {/* A row of its own, so the query and the server's complaint about it sit
          together and the rest of the bar keeps its place. */}
      <div className="query-row">
        <input
          type="text"
          className="mono"
          aria-label="Filter query"
          placeholder={QUERY_EXAMPLE}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-invalid={Boolean(queryError)}
          style={{ flex: 1, minWidth: 220 }}
        />
        {queryError && (
          <span className="query-error" role="alert">{queryError}</span>
        )}
      </div>
    </div>
  );
}
