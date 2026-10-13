/** The leaderboard's inner column: one cell per outer run summing its inner
 *  runs (`5 · 4 running · 1 failed`), shown while an outer run is loaded. */
import type { ExperimentRow } from "../types";
import { fleetCounts } from "./leaderboardColumns";

/** The column's id (the `show=`/`hide=` key). */
export const INNER_COLUMN = "c:inner";
export const isInnerRunId = (id: string) => id === INNER_COLUMN;

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
  return {
    total: counts.total, parts,
    text: [String(counts.total), ...parts.map((p) => p.text)].join(" · "),
    label: [runs, ...parts.map((p) => p.text)].join(", "),
  };
}
