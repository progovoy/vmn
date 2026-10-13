/** The leaderboard's inner column: one cell per outer run summing its inner
 *  runs (`5 · 4 running · 1 failed`), shown while an outer run is loaded. */
import type { ExperimentRow } from "../types";
import { sweepIncompleteLabel, sweepIncompleteSpoken } from "../util/sweepProgress";
import { fleetCounts } from "./leaderboardColumns";

/** The column's id (the `show=`/`hide=` key). */
export const INNER_COLUMN = "c:inner";
export const isInnerRunId = (id: string) => id === INNER_COLUMN;

/** The five count columns the inner column replaced (plan 20 C2), still in
 *  older saved views and links. */
const LEGACY_COUNTS = ["c:total", "c:waiting", "c:running", "c:done", "c:failed"];

/** Whether the inner column shows: its own `show=`/`hide=` entry wins, then
 *  an old count's (`show=` of any, `hide=` of every one), then outer rows. */
export function innerVisible(shown: ReadonlySet<string>, hidden: ReadonlySet<string>, hasOuter: boolean) {
  if (shown.has(INNER_COLUMN)) return true;
  if (hidden.has(INNER_COLUMN)) return false;
  if (LEGACY_COUNTS.some((k) => shown.has(k))) return true;
  return hasOuter && !LEGACY_COUNTS.every((k) => hidden.has(k));
}

export const INNER_RUNS_HELP = "Counts of this run's inner runs (sweep trials, fleet pods)";

/** Whether any loaded row is an outer run — the column's default. */
export const anyOuter = (rows: readonly ExperimentRow[] | undefined) =>
  Boolean(rows?.some((r) => r.kind === "outer"));

/** The states the cell names, in the order it names them. */
const STATES = ["running", "failed", "waiting", "done"] as const;
export type InnerState = (typeof STATES)[number];

export interface InnerRunSummary {
  total: number;
  /** The states with at least one run. */
  parts: { state: InnerState; count: number; text: string }[];
  /** What the cell shows: `5 · 4 running · 1 failed`. */
  text: string;
  /** An incomplete sweep's `16/20 · incomplete`, else null. */
  incomplete: string | null;
  /** What a screen reader says: `5 inner runs, 4 running, 1 failed`. */
  label: string;
}

/** The inner cell of *r*; null for a run without inner runs. */
export function innerRunSummary(r: ExperimentRow): InnerRunSummary | null {
  const counts = fleetCounts(r);
  if (!counts) return null;
  const parts = STATES.filter((s) => counts[s] > 0)
    .map((state) => ({ state, count: counts[state], text: `${counts[state]} ${state}` }));
  const runs = `${counts.total} inner run${counts.total === 1 ? "" : "s"}`;
  const incomplete = sweepIncompleteLabel(r);
  const spoken = sweepIncompleteSpoken(r);
  return {
    total: counts.total, parts, incomplete,
    text: [String(counts.total), ...parts.map((p) => p.text), ...(incomplete ? [incomplete] : [])].join(" · "),
    label: [runs, ...parts.map((p) => p.text), ...(spoken ? [spoken] : [])].join(", "),
  };
}
