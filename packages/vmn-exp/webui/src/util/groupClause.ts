/** A group as a filter clause (plan 23 §3.4): a group too big to unfold in
 *  place opens as its clause, a token in the filter grammar. The server's
 *  `clause` (S7) is preferred where it is served; this derives the same text
 *  from the grouping and the group's key. */
import { NONE_GROUP, groupKeyText } from "../apiGroups";
import { commitText, joinClauses, stateFromValues, type FilterValues } from "./filterTokens";
import { fieldPath } from "./brushQuery";
import { eqClause } from "./searchQuery";

/** Groups up to this many runs unfold in place; bigger ones open as a filter. */
export const BIG_GROUP = 50;

const QUOTED_FIELDS = new Set(["status", "branch", "failure_sig"]);
const KEYED = /^(tags|params)\.(.+)$/;
/** How a group key spells a number or boolean: JSON (the server's `json.dumps`). */
const JSON_SCALAR = /^(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false)$/;

/** `params.lr`, or `params."train/lr"` for a key a bare name can't hold. */
function fieldText(field: string): string | null {
  const m = field.match(KEYED);
  if (!m) return QUOTED_FIELDS.has(field) ? field : null;
  return fieldPath(m[1] as "tags" | "params", m[2]);
}

/** The clause selecting group *key* of grouping *field*; null for a link
 *  grouping and for text no literal can hold. */
export function groupClause(field: string, key: string): string | null {
  const name = fieldText(field);
  if (!name) return null;
  if (key === NONE_GROUP) return `${name} = null`;
  const text = groupKeyText(key);
  if (field.startsWith("params.") && JSON_SCALAR.test(text)) return `${name} = ${text}`;
  return eqClause(name, text);
}

/** The URL's filter values with *clause* added where the filter bar files
 *  it (a status clause as the status, the rest into `q`). */
export function addFilterClause(values: FilterValues, clause: string): Required<FilterValues> {
  const s = commitText(stateFromValues(values), clause);
  return { status: s.statuses.join(","), query: joinClauses(s.clauses), search: s.search, branch: s.branch };
}
