/** The leaderboard's one filter grammar (plan 20 D10): every filter is a
 *  clause shown as a token. Status, branch and the free-text search keep their
 *  own URL params (`status`, `branch`, `search`) for old links; every other
 *  clause travels in `q`. A hand-typed `status = "failed"` is filed exactly
 *  where the status shortcut would have put it. */
import type { RunState } from "../types";
import { quoteLiteral } from "./searchQuery";
import { unknownFields } from "./queryFields";

/** Every status, in display order. */
export const STATUS_ORDER: RunState[] = ["running", "stuck", "failed", "succeeded", "created"];

export interface FilterState {
  statuses: RunState[];
  branch: string;
  search: string;
  /** The rest of the query, one top-level conjunct each. */
  clauses: string[];
}

export const EMPTY_FILTER: FilterState = { statuses: [], branch: "", search: "", clauses: [] };

export type TokenKind = "status" | "branch" | "search" | "query" | "archived";
export interface FilterToken { kind: TokenKind; text: string }

/** What the URL carries (the `?status=` CSV, `q`, `branch`, `search`). */
export interface FilterValues { search?: string; branch?: string; status?: string; query?: string }

type Clause =
  | { kind: "status"; statuses: RunState[] }
  | { kind: "branch"; branch: string }
  | { kind: "search"; text: string }
  | { kind: "query"; clause: string };

/** *text*'s top-level `and` conjuncts. Quotes and parens are kept whole, and a
 *  query with a top-level `or` stays one clause, since `and` binds tighter. */
export function splitConjuncts(text: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote = "";
  let start = 0;
  let hasOr = false;
  const wordAt = (i: number, word: string) =>
    text.slice(i, i + word.length).toLowerCase() === word
    && /\s/.test(text[i - 1] ?? "") && /\s/.test(text[i + word.length] ?? "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) { if (c === quote) quote = ""; continue; }
    if (c === '"' || c === "'") quote = c;
    else if (c === "(") depth++;
    else if (c === ")") depth--;
    else if (depth === 0 && wordAt(i, "or")) hasOr = true;
    else if (depth === 0 && wordAt(i, "and")) {
      parts.push(text.slice(start, i));
      start = i + 3;
    }
  }
  parts.push(text.slice(start));
  if (hasOr) return text.trim() ? [text.trim()] : [];
  return parts.map((p) => p.trim()).filter(Boolean);
}

const VALUE = String.raw`(?:"([^"]*)"|'([^']*)'|([\w./-]+))`;
const equality = (field: string) => new RegExp(String.raw`^${field}\s*==?\s*${VALUE}$`, "i");
const STATUS_EQ = equality("status");
const BRANCH_EQ = equality("branch");
const STATUS_IN = /^status\s+in\s*\(([^)]*)\)$/i;
const TEXT_MATCH = /^text\s*~\s*(?:"([^"]*)"|'([^']*)')$/i;

const valueOf = (m: RegExpMatchArray) => m[1] ?? m[2] ?? m[3];
const unquote = (v: string) => v.trim().replace(/^(["'])(.*)\1$/, "$2");
const isStatus = (v: string): v is RunState => (STATUS_ORDER as string[]).includes(v);
const inDisplayOrder = (statuses: readonly string[]) => STATUS_ORDER.filter((s) => statuses.includes(s));

/** What one clause filters: a status, a branch, the free-text search, or
 *  anything else, kept verbatim. */
export function readClause(clause: string): Clause {
  const c = clause.trim();
  const query: Clause = { kind: "query", clause: c };
  const eq = c.match(STATUS_EQ);
  const inList = c.match(STATUS_IN);
  const values = eq ? [valueOf(eq)] : inList ? inList[1].split(",").map(unquote) : null;
  if (values) return values.every(isStatus) ? { kind: "status", statuses: inDisplayOrder(values) } : query;
  const branch = c.match(BRANCH_EQ);
  if (branch) return { kind: "branch", branch: valueOf(branch) };
  const text = c.match(TEXT_MATCH);
  if (text) return { kind: "search", text: text[1] ?? text[2] };
  return query;
}

/** Whether *text* is free text to search for rather than a query. */
export const isPlainText = (text: string) =>
  !/[=<>!~]/.test(text) && !/\bin\s*\(/i.test(text) && !/\S\s+contains\s+\S/i.test(text);

function addClause(state: FilterState, clause: Clause): FilterState {
  switch (clause.kind) {
    case "status": return { ...state, statuses: clause.statuses };
    case "branch": return { ...state, branch: clause.branch };
    case "search": return { ...state, search: clause.text };
    default:
      return state.clauses.includes(clause.clause)
        ? state : { ...state, clauses: [...state.clauses, clause.clause] };
  }
}

/** *state* with the typed *text* added: free text becomes the search, each
 *  query conjunct goes where its shortcut would have put it. */
export function commitText(state: FilterState, text: string): FilterState {
  const t = text.trim();
  if (!t) return state;
  if (isPlainText(t)) return { ...state, search: t };
  return splitConjuncts(t).map(readClause).reduce(addClause, state);
}

/** *state* with what was typed in the box added: like commitText, except
 *  that text comparing a word no field matches (`lr=0.1`) is searched for
 *  as text rather than sent as a query the server refuses. */
export function commitTyped(state: FilterState, text: string): FilterState {
  const t = text.trim();
  return t && unknownFields(t).length ? { ...state, search: t } : commitText(state, t);
}

/** The URL's filters as one state. */
export function stateFromValues(values: FilterValues = {}): FilterState {
  const statuses = inDisplayOrder((values.status ?? "").split(","));
  const base = { statuses, branch: values.branch ?? "", search: values.search ?? "", clauses: [] };
  return commitText(base, values.query ?? "");
}

const literal = (text: string) => quoteLiteral(text) ?? `"${text}"`;

export const statusText = (statuses: readonly string[]) =>
  statuses.length === 1
    ? `status = "${statuses[0]}"`
    : `status in (${statuses.map((s) => `"${s}"`).join(", ")})`;

/** One token per active filter, worded as the clause that would type it. */
export function filterTokens(state: FilterState, archived: boolean): FilterToken[] {
  const tokens: FilterToken[] = [];
  if (state.statuses.length) tokens.push({ kind: "status", text: statusText(state.statuses) });
  if (state.branch) tokens.push({ kind: "branch", text: `branch = ${literal(state.branch)}` });
  if (state.search) tokens.push({ kind: "search", text: `text ~ ${literal(state.search)}` });
  state.clauses.forEach((c) => tokens.push({ kind: "query", text: c }));
  if (archived) tokens.push({ kind: "archived", text: "archived" });
  return tokens;
}

/** *state* without *token*'s filter (the archived token lives outside it). */
export function removeToken(state: FilterState, token: FilterToken): FilterState {
  switch (token.kind) {
    case "status": return { ...state, statuses: [] };
    case "branch": return { ...state, branch: "" };
    case "search": return { ...state, search: "" };
    case "query": return { ...state, clauses: state.clauses.filter((c) => c !== token.text) };
    default: return state;
  }
}

/** The query clauses as `q`, parenthesizing a clause with a top-level `or`. */
export function joinClauses(clauses: readonly string[]): string {
  if (clauses.length === 1) return clauses[0];
  return clauses.map((c) => (/\sor\s/i.test(c) ? `(${c})` : c)).join(" and ");
}
