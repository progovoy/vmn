/** Autocomplete for the leaderboard's query box — the grammar of
 *  version_stamp/core/experiment_query.py, reduced to "what can come next". */

/** Non-metric row fields the query language knows (its ROW_FIELDS). */
export const ROW_FIELDS = [
  "status", "note", "branch", "verstr", "code_verstr", "timestamp", "idx",
  "base_version", "kind", "depth", "tree_status", "parent", "children",
  "exit_code", "duration_sec", "started_at", "finished_at", "heartbeat",
  "last_metric_at", "host", "pid", "command", "stale_sec",
  "heartbeat_interval_sec", "user_meta",
];

export const OPERATORS = ["=", "!=", "<", "<=", ">", ">=", "~", "!~", "in", "not in", "contains"];
const CONNECTIVES = ["and", "or"];
const STARTERS = new Set(["", "and", "or", "not", "("]);

export interface SuggestFacets {
  metric_keys?: readonly string[];
  param_keys?: readonly string[];
}

const WORD = /[\w.]*$/;
const TOKEN = /"[^"]*"|'[^']*'|[()]|[<>!=~]+|[\w.+-]+/g;

function lastToken(text: string): string {
  const tokens = text.match(TOKEN);
  return tokens ? tokens[tokens.length - 1].toLowerCase() : "";
}

const isOperator = (t: string) => /^[<>!=~]+$/.test(t) || t === "in" || t === "contains";
const isLiteral = (t: string) =>
  /^["']/.test(t) || t === ")" || /^[-+]?\d/.test(t) || ["true", "false", "null"].includes(t);

function fieldsFor(facets: SuggestFacets): string[] {
  return [
    ...(facets.metric_keys ?? []).map((k) => `metrics.${k}`),
    ...(facets.param_keys ?? []).map((k) => `params.${k}`),
    ...ROW_FIELDS,
  ];
}

/** What may be typed at *caret*: fields at the start of a term, operators
 *  after a field, `and`/`or` after a value — narrowed by the word typed. */
export function suggest(text: string, caret: number, facets: SuggestFacets): string[] {
  const head = text.slice(0, caret);
  const word = head.match(WORD)![0].toLowerCase();
  const prev = lastToken(head.slice(0, head.length - word.length));

  let pool: string[];
  if (STARTERS.has(prev)) pool = fieldsFor(facets);
  else if (isOperator(prev) || prev === "not") return [];
  else if (isLiteral(prev)) pool = CONNECTIVES;
  else pool = OPERATORS;

  if (!word) return pool;
  return pool.filter((s) => s.toLowerCase().includes(word) && s.toLowerCase() !== word);
}

/** *text* with the word at *caret* replaced by *choice* and a trailing space. */
export function applySuggestion(text: string, caret: number, choice: string) {
  const head = text.slice(0, caret);
  const start = head.length - head.match(WORD)![0].length;
  const inserted = `${choice} `;
  return {
    text: text.slice(0, start) + inserted + text.slice(caret),
    caret: start + inserted.length,
  };
}
