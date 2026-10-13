import { useEffect, useMemo, useState } from "react";
import type { ExperimentRow } from "../types";
import { useDebounce } from "../hooks/useDebounce";
import { useFilterGrammar, type FilterReports } from "../hooks/useFilterGrammar";
import { filterTokens, removeToken, type FilterToken, type FilterValues } from "../util/filterTokens";
import type { SuggestFacets } from "../util/querySuggest";
import { fieldHint } from "../util/queryFields";
import FilterShortcuts from "./FilterShortcuts";
import QueryBar from "./QueryBar";
import QueryFieldHint from "./QueryFieldHint";
import SimilarToggle from "./SimilarToggle";

export type { FilterValues };

/** The box's hint: free text, or a query that uses most of the language. */
const QUERY_HINT = 'Search, or metrics.loss < 0.5 and status = "succeeded"';
const SIMILAR_HINT = "Describe a run: what it changes and why...";

const NO_FACETS: SuggestFacets = {};

/** The leaderboard's filter bar: one grammar (plan 20 D10). Every filter is a
 *  token in the query bar; the status, branch and archived shortcuts write
 *  theirs. Each filter is reported for the server to apply; *rows* only feed
 *  the branch list when no branches are given. */
export default function LeaderboardFilter({
  rows = [], queryError, branches: knownBranches, facets = NO_FACETS, initial, archived = false,
  onArchivedChange, onSimilarChange, ...reports
}: FilterReports & {
  rows?: ExperimentRow[];
  /** What the server said about the query it refused; shown beside the bar. */
  queryError?: string | null;
  /** Every branch of the app (server facets); else the rows' branches. */
  branches?: string[] | null;
  /** Field names the query box suggests. */
  facets?: SuggestFacets;
  /** Values to start from (the URL's), so a restored view shows its filters. */
  initial?: FilterValues;
  /** Whether archived runs are shown; the shortcut appears with *onArchivedChange*. */
  archived?: boolean;
  onArchivedChange?: (on: boolean) => void;
  /** The "similar" mode's text, debounced and trimmed, or null outside the
   *  mode; the mode's toggle appears with this callback. The typed filter
   *  text is kept apart, so leaving the mode restores it. */
  onSimilarChange?: (text: string | null) => void;
}) {
  const [similarOn, setSimilarOn] = useState(false);
  const [similarText, setSimilarText] = useState("");
  const grammar = useFilterGrammar(initial, similarOn, reports);
  const { state, setState } = grammar;
  // Each change scores the app's runs: wait for a pause, like the query box.
  const debouncedSimilar = useDebounce(similarText, 300);
  const similar = similarOn ? debouncedSimilar.trim() : null;
  useEffect(() => { onSimilarChange?.(similar); }, [similar, onSimilarChange]);

  const rowBranches = useMemo(
    () => [...new Set(rows.map((r) => r.branch).filter((b): b is string => Boolean(b)))].sort(),
    [rows],
  );
  const tokens = filterTokens(state, archived);
  const remove = (t: FilterToken) =>
    t.kind === "archived" ? onArchivedChange?.(false) : setState((s) => removeToken(s, t));
  const clear = () => {
    grammar.clear();
    setSimilarText("");
    if (archived) onArchivedChange?.(false);
  };
  const typedHint = similarOn ? null : fieldHint(grammar.draft, facets);
  const hasFilter = tokens.length > 0 || grammar.draft || (similarOn && similarText);

  return (
    <div className="toolbar filter-bar">
      <QueryBar
        tokens={tokens}
        onRemove={remove}
        text={similarOn ? similarText : grammar.draft}
        onText={similarOn ? setSimilarText : grammar.setDraft}
        onSubmit={similarOn ? undefined : grammar.commit}
        facets={facets}
        placeholder={similarOn ? SIMILAR_HINT : QUERY_HINT}
        suggestions={!similarOn}
        error={queryError}
        hint={typedHint && <QueryFieldHint hint={typedHint} onApply={grammar.apply} />}
        inside={onSimilarChange && <SimilarToggle on={similarOn} onToggle={() => setSimilarOn((on) => !on)} />}
      />
      <FilterShortcuts
        statuses={state.statuses}
        onStatuses={(statuses) => setState((s) => ({ ...s, statuses }))}
        branch={state.branch}
        branches={knownBranches ?? rowBranches}
        onBranch={(branch) => setState((s) => ({ ...s, branch }))}
        archived={archived}
        onArchived={onArchivedChange}
      />
      {hasFilter && (
        <button className="filter-clear" title="Clear filters" onClick={clear}>
          ✕
        </button>
      )}
    </div>
  );
}
