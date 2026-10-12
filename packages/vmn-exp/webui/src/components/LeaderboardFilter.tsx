import { useEffect, useMemo, useState } from "react";
import type { ExperimentRow, RunState } from "../types";
import { useDebounce } from "../hooks/useDebounce";
import type { SuggestFacets } from "../util/querySuggest";
import QueryInput from "./QueryInput";

/** Every status, in display order. Static on purpose: the list endpoint answers
 *  the `?status=` filter, so the rows on hand no longer show what else exists. */
const STATUS_ORDER: RunState[] = [
  "running", "stuck", "failed", "succeeded", "created",
];

/** The syntax hint on the query box: a query that uses most of the language. */
const QUERY_EXAMPLE = 'metrics.loss < 0.5 and status = "succeeded"';
const SEARCH_HINT = "Search note, verstr, branch...";
const SIMILAR_HINT = "Describe a run: what it changes and why...";

const NO_FACETS: SuggestFacets = {};

export interface FilterValues {
  search?: string;
  branch?: string;
  /** Statuses as the `?status=` CSV. */
  status?: string;
  query?: string;
}

const parseStatuses = (csv = "") =>
  STATUS_ORDER.filter((s) => csv.split(",").includes(s));

/** The leaderboard's filter bar. Every filter is reported for the server to
 *  apply; *rows* only feed the branch list when no facets are given. */
export default function LeaderboardFilter({
  rows = [], onStatusChange, onQueryChange, onSearchChange, onBranchChange,
  queryError, branches: knownBranches, facets = NO_FACETS, initial, archived, onArchivedChange,
  onSimilarChange,
}: {
  rows?: ExperimentRow[];
  /** Picked statuses as the `?status=` CSV the list endpoint takes. */
  onStatusChange?: (csv: string) => void;
  /** The typed query as the `?q=` the list endpoint takes, debounced. */
  onQueryChange?: (query: string) => void;
  /** The search box text, debounced, for the server to search every run. */
  onSearchChange?: (text: string) => void;
  onBranchChange?: (branch: string) => void;
  /** What the server said about the query it refused; shown beside the box. */
  queryError?: string | null;
  /** Every branch of the app (server facets); else the rows' branches. */
  branches?: string[] | null;
  /** Field names the query box suggests. */
  facets?: SuggestFacets;
  /** Values to start from (the URL's), so a restored view shows its filters. */
  initial?: FilterValues;
  /** Whether archived runs are shown; the toggle appears with *onArchivedChange*. */
  archived?: boolean;
  onArchivedChange?: (on: boolean) => void;
  /** The "similar" mode's text, debounced and trimmed, or null outside the
   *  mode; the mode's toggle appears with this callback. The search text is
   *  kept apart, so leaving the mode restores it. */
  onSimilarChange?: (text: string | null) => void;
}) {
  const [search, setSearch] = useState(initial?.search ?? "");
  const [branch, setBranch] = useState(initial?.branch ?? "");
  const [statuses, setStatuses] = useState<RunState[]>(() => parseStatuses(initial?.status));
  const [query, setQuery] = useState(initial?.query ?? "");
  const [similarOn, setSimilarOn] = useState(false);
  const [similarText, setSimilarText] = useState("");
  const debouncedSearch = useDebounce(search);
  // Each change scores the app's runs: wait for a pause, like the query box.
  const debouncedSimilar = useDebounce(similarText, 300);
  // Long enough that a whole field name is typed before it costs a request.
  const debouncedQuery = useDebounce(query, 300);

  const rowBranches = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => { if (r.branch) set.add(r.branch); });
    return [...set].sort();
  }, [rows]);
  const branches = knownBranches ?? rowBranches;

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
    onSearchChange?.(debouncedSearch.trim());
  }, [debouncedSearch, onSearchChange]);

  useEffect(() => {
    onBranchChange?.(branch);
  }, [branch, onBranchChange]);

  useEffect(() => {
    onSimilarChange?.(similarOn ? debouncedSimilar.trim() : null);
  }, [similarOn, debouncedSimilar, onSimilarChange]);

  const clear = () => {
    setSearch("");
    setBranch("");
    setStatuses([]);
    setQuery("");
    setSimilarText("");
  };

  const hasFilter = search || branch || query || statuses.length > 0 || (similarOn && similarText);

  return (
    <div className="toolbar filter-bar">
      <input
        type="text"
        className="filter-control"
        aria-label="Search runs"
        placeholder={similarOn ? SIMILAR_HINT : SEARCH_HINT}
        value={similarOn ? similarText : search}
        onChange={(e) => (similarOn ? setSimilarText : setSearch)(e.target.value)}
        style={{ flex: 1, minWidth: 160, maxWidth: 300 }}
      />
      {onSimilarChange && (
        <button
          className="status-toggle"
          aria-pressed={similarOn}
          title="find runs similar to a description (intent, name, note, tags, commits)"
          onClick={() => setSimilarOn((on) => !on)}
        >
          similar
        </button>
      )}
      <select
        role="combobox"
        className="filter-control"
        value={branch}
        onChange={(e) => setBranch(e.target.value)}
        style={{ minWidth: 120 }}
      >
        <option value="">All branches</option>
        {branch && !branches.includes(branch) && <option value={branch}>{branch}</option>}
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
      {onArchivedChange && (
        <button
          className="status-toggle archived-toggle"
          aria-pressed={Boolean(archived)}
          title="include archived runs"
          onClick={() => onArchivedChange(!archived)}
        >
          archived
        </button>
      )}
      {hasFilter && (
        <button className="filter-clear" title="Clear filters" onClick={clear}>
          ✕
        </button>
      )}
      {/* A row of its own, so the query and the server's complaint about it sit
          together and the rest of the bar keeps its place. */}
      <div className="query-row">
        <QueryInput
          value={query}
          onChange={setQuery}
          facets={facets}
          invalid={Boolean(queryError)}
          placeholder={QUERY_EXAMPLE}
        />
        {queryError && (
          <span className="query-error" role="alert">{queryError}</span>
        )}
      </div>
    </div>
  );
}
