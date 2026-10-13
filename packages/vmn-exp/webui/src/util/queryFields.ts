/** Which compared words of a typed query are no field the query language
 *  knows — so `lr=0.1` searches text instead of failing on the server (plan
 *  20 D10). Mirrors `_field` in vmn_exp/core/query.py. */
import { ROW_FIELDS, type SuggestFacets } from "./querySuggest";

const BARE = new Set([...ROW_FIELDS, "text"]);
const PREFIXES = new Set(["metrics", "params", "tags", "env", "comments", "inputs", "outputs"]);
const TOKEN = /"[^"]*"|'[^']*'|[()]|[<>!=~]+|[\w.+-]+/g;

const isOperator = (t: string) => /^[<>!=~]+$/.test(t) || ["in", "contains", "not"].includes(t.toLowerCase());
const KEYWORDS = new Set(["and", "or", "not", "in", "contains", "true", "false", "null"]);
const isWord = (t: string) => /^[A-Za-z_][\w.]*$/.test(t) && !KEYWORDS.has(t.toLowerCase());

/** Whether *name* reads a field: a row field or `<prefix>.<key>…`; a word
 *  starting with "." continues a quoted key (`outputs."m.pkl".digest`). */
function knownField(name: string): boolean {
  if (name.startsWith(".")) return true;
  const [head, ...rest] = name.split(".");
  return rest.length ? PREFIXES.has(head) : BARE.has(name);
}

/** The compared words of *text* (the word before each operator) that no
 *  field matches, in order. */
export function unknownFields(text: string): string[] {
  const tokens = text.match(TOKEN) ?? [];
  const out: string[] = [];
  tokens.forEach((t, i) => {
    const prev = tokens[i - 1];
    if (!prev || !isOperator(t) || isOperator(prev) || !isWord(prev) && !prev.startsWith(".")) return;
    if (!knownField(prev) && !out.includes(prev)) out.push(prev);
  });
  return out;
}

export interface FieldHint {
  field: string;
  /** *text* with the field as the app's param or metric of that name. */
  suggestion: string | null;
}

/** The first unknown field of *text*, with the clause it likely meant. */
export function fieldHint(text: string, facets: SuggestFacets): FieldHint | null {
  const [field] = unknownFields(text);
  if (!field) return null;
  const prefix = facets.param_keys?.includes(field) ? "params"
    : facets.metric_keys?.includes(field) ? "metrics" : null;
  const at = text.search(new RegExp(String.raw`(^|[\s(])${field.replace(/[.]/g, "\\.")}(?![\w.])`));
  const start = at < 0 ? -1 : at + (/[\s(]/.test(text[at]) ? 1 : 0);
  const suggestion = prefix && start >= 0
    ? `${text.slice(0, start)}${prefix}.${text.slice(start)}`.trim() : null;
  return { field, suggestion };
}
