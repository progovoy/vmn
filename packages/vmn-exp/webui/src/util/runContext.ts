/** An inner run's place in its job (plan 23 W7, §3.3): the order the job's
 *  Runs tab showed, carried to the run page as `?from=<board order>&at=<i>`
 *  (the run's index in it), and the clauses that place and rank it. Pure. */
import type { HistBin } from "../apiJob";
import { quoteLiteral } from "./searchQuery";

/** The board order a run link carries: the job (scope), filters and sort. */
export interface BoardOrder {
  scope: string;
  q?: string;
  status?: string;
  sort?: string;
  order?: "asc" | "desc";
}

const KEYS = ["scope", "q", "status", "sort", "order"] as const;

/** The job's own default order: newest first (the board's `idx` sort). */
export const defaultOrder = (scope: string): BoardOrder => ({ scope, sort: "idx" });

export function encodeFrom(o: BoardOrder): string {
  const p = new URLSearchParams();
  for (const k of KEYS) if (o[k]) p.set(k, o[k]!);
  return String(p);
}

/** The order in `from=`, null when absent or of another job than *scope*. */
export function decodeFrom(raw: string | null, scope: string): BoardOrder | null {
  if (!raw) return null;
  const p = new URLSearchParams(raw);
  if (p.get("scope") !== scope) return null;
  const o: BoardOrder = { scope };
  for (const k of KEYS.slice(1)) {
    const v = p.get(k);
    if (v) (o as unknown as Record<string, string>)[k] = v;
  }
  if (o.order && o.order !== "asc" && o.order !== "desc") delete o.order;
  return o;
}

/** `?from=…&at=…`: a run link at index *at* of order *o*. */
export const runContextSearch = (o: BoardOrder, at: number) =>
  `?${new URLSearchParams({ from: encodeFrom(o), at: String(at) })}`;

/** The runs better than *value* on *metric* toward *goal*. */
export function betterClause(metric: string, value: number, goal: "min" | "max"): string | null {
  const name = /^\w+$/.test(metric) ? metric : quoteLiteral(metric);
  return name && `metrics.${name} ${goal === "min" ? "<" : ">"} ${value}`;
}

/** The runs ahead of run *idx* in the default order (newest first). */
export const aheadClause = (idx: number) => `idx > ${idx}`;

/** *value* as a fraction along *bins*' span (clamped), null without bins. */
export function histMarkAt(bins: readonly HistBin[], value: number): number | null {
  if (!bins.length) return null;
  const lo = bins[0].lo;
  const span = bins[bins.length - 1].hi - lo;
  if (!(span > 0)) return 0.5;
  return Math.min(Math.max((value - lo) / span, 0), 1);
}
