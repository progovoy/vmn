/** The leaderboard's inner-run count columns: which they are, the header
 *  group over them, and what their cells say. */
import type { ExperimentRow } from "../types";
import { fleetCounts } from "./leaderboardColumns";

/** The fleet columns that count an outer run's inner runs (the dates aren't). */
export const INNER_RUN_COLS = ["total", "waiting", "running", "done", "failed"] as const;
export type InnerRunCol = (typeof INNER_RUN_COLS)[number];

const INNER_IDS = new Set<string>(INNER_RUN_COLS.map((c) => `c:${c}`));
export const isInnerRunId = (id: string) => INNER_IDS.has(id);

export const INNER_RUNS_LABEL = "Inner runs";
export const INNER_RUNS_HELP = "Counts of this run's inner runs (sweep trials, fleet pods)";

/** Whether any loaded row is an outer run — the count columns' default. */
export const anyOuter = (rows: readonly ExperimentRow[] | undefined) =>
  Boolean(rows?.some((r) => r.kind === "outer"));

/** One cell of the group row: *span* columns from *start*. */
export interface HeadGroup {
  start: number;
  span: number;
  /** True for a block of adjacent count columns. */
  inner: boolean;
}

/** The group row over *ids*: one cell per contiguous block of count columns
 *  (a block dragged apart gets a label of its own), one per other column;
 *  null when no count column is shown. */
export function headGroups(ids: readonly string[]): HeadGroup[] | null {
  const out: HeadGroup[] = [];
  ids.forEach((id, i) => {
    const inner = isInnerRunId(id);
    const last = out[out.length - 1];
    if (inner && last?.inner) last.span += 1;
    else out.push({ start: i, span: 1, inner });
  });
  return out.some((g) => g.inner) ? out : null;
}

/** What a count cell shows: the count for an outer run, nothing otherwise. */
export function innerRunCount(r: ExperimentRow, col: string): string {
  const counts = fleetCounts(r);
  return counts && col in counts ? String(counts[col as InnerRunCol]) : "";
}
