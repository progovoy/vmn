import type { ReactNode } from "react";
import type { FilterToken } from "../util/filterTokens";
import type { SuggestFacets } from "../util/querySuggest";
import QueryInput from "./QueryInput";
import "./QueryBar.css";

/** The leaderboard's query bar: the active filters as removable tokens, then
 *  the text box that types more of them (*inside*, e.g. the similar toggle,
 *  sits in the box). */
export default function QueryBar({
  tokens, onRemove, text, onText, onSubmit, facets, placeholder, suggestions, error, hint, inside,
}: {
  tokens: readonly FilterToken[];
  onRemove: (token: FilterToken) => void;
  text: string;
  onText: (text: string) => void;
  onSubmit?: () => void;
  facets: SuggestFacets;
  placeholder: string;
  suggestions: boolean;
  /** What the server said about the query it refused. */
  error?: string | null;
  /** A note on how the typed text is read, beside the box. */
  hint?: ReactNode;
  inside?: ReactNode;
}) {
  const last = tokens[tokens.length - 1];
  return (
    <div className="query-bar">
      <div className="query-bar-box">
        <ul className="query-tokens" aria-label="Active filters">
          {tokens.map((t) => (
            <li key={`${t.kind}:${t.text}`} className={`query-token ${t.kind}`} data-token={t.text}>
              <span className="mono">{t.text}</span>
              <button type="button" aria-label={`Remove filter ${t.text}`} onClick={() => onRemove(t)}>
                ✕
              </button>
            </li>
          ))}
        </ul>
        <QueryInput
          value={text}
          onChange={onText}
          facets={facets}
          invalid={Boolean(error)}
          placeholder={placeholder}
          onSubmit={onSubmit}
          onEmptyBackspace={last ? () => onRemove(last) : undefined}
          className="filter-control"
          suggestions={suggestions}
        />
        {inside}
      </div>
      {error && <span className="query-error" role="alert">{error}</span>}
      {hint && <span className="query-hint">{hint}</span>}
    </div>
  );
}
