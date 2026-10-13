/** The query help's content (plan 20 C5): this app's fields, and examples
 *  built from its real keys and the loaded rows' values. */
import type { ExperimentRow } from "../types";
import { metricGoal } from "../util";
import type { SuggestFacets } from "./querySuggest";
import { quoteLiteral } from "./searchQuery";

export interface QueryHelpData {
  metrics: string[];
  params: string[];
  tags: string[];
  examples: string[];
}

export interface QueryHelpInputs {
  facets: SuggestFacets;
  branches: readonly string[];
  rows: readonly ExperimentRow[];
  schema?: Record<string, { goal?: string }> | null;
  /** The board's primary metric, the metric example's first choice. */
  primary?: string | null;
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/** *value* as a query literal: numbers and bools bare, strings quoted. */
export function literal(value: unknown): string | null {
  if (isFiniteNumber(value) || typeof value === "boolean") return String(value);
  return typeof value === "string" ? quoteLiteral(value) : null;
}

/** `metrics.<m> < median`, toward the metric's goal: the primary metric, else
 *  the first with a goal, else the first with values. */
function metricExample({ facets, rows, schema = null, primary }: QueryHelpInputs): string | null {
  const keys = facets.metric_keys ?? [];
  const ordered = [
    ...(primary && keys.includes(primary) ? [primary] : []),
    ...keys.filter((k) => metricGoal(schema, k)), ...keys,
  ];
  for (const key of ordered) {
    const mid = median(rows.map((r) => r.metrics?.[key]).filter(isFiniteNumber));
    if (mid === null) continue;
    const op = metricGoal(schema, key) === "max" ? ">" : "<";
    return `metrics.${key} ${op} ${Number(mid.toPrecision(2))}`;
  }
  return null;
}

/** `<prefix>.<key> = <value>` for the first key a row has a value for. */
function valueExample(prefix: string, keys: readonly string[], rows: readonly ExperimentRow[],
  read: (r: ExperimentRow) => Record<string, unknown> | undefined): string | null {
  for (const key of keys) {
    for (const r of rows) {
      const lit = literal(read(r)?.[key]);
      if (lit) return `${prefix}.${key} = ${lit}`;
    }
  }
  return null;
}

/** Every tag key on the loaded rows, in first-seen order. */
const tagKeys = (rows: readonly ExperimentRow[]) =>
  [...new Set(rows.flatMap((r) => Object.keys(r.tags ?? {})))];

/** The help's fields and three examples, from real keys where the app has them. */
export function queryHelpData(inputs: QueryHelpInputs): QueryHelpData {
  const { facets, branches, rows } = inputs;
  const tags = tagKeys(rows);
  const branch = branches[0] && quoteLiteral(branches[0]);
  const candidates = [
    metricExample(inputs),
    valueExample("params", facets.param_keys ?? [], rows, (r) => r.params),
    branch ? `status = "failed" and branch = ${branch}` : 'status = "failed"',
    valueExample("tags", tags, rows, (r) => r.tags),
    'note ~ "baseline"',
  ];
  return {
    metrics: (facets.metric_keys ?? []).map((k) => `metrics.${k}`),
    params: (facets.param_keys ?? []).map((k) => `params.${k}`),
    tags: tags.map((k) => `tags.${k}`),
    examples: candidates.filter((e): e is string => Boolean(e)).slice(0, 3),
  };
}
