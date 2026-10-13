/** The leaderboard's inner-run count columns: which they are, when they
 *  show, the header group over them, and what their cells say. */
import type { ExperimentRow } from "../types";
import { sweepIncompleteLabel, sweepIncompleteSpoken } from "../util/sweepProgress";
import { fleetCounts } from "./leaderboardColumns";

/** The fleet columns that count an outer run's inner runs (the dates aren't). */
export const INNER_RUN_COLS = ["total", "waiting", "running", "done", "failed"] as const;
export type InnerRunCol = (typeof INNER_RUN_COLS)[number];

const INNER_IDS = new Set<string>(INNER_RUN_COLS.map((c) => `c:${c}`));
export const isInnerRunId = (id: string) => INNER_IDS.has(id);

/** The one inner column the counts were merged into for a while (plan 20
 *  C2, reverted): links and views saved then use it for all five. */
const MERGED_INNER = "c:inner";

/** Whether count column *id* shows: its own `show=`/`hide=` wins, then
 *  `c:inner`'s, then whether an outer run is loaded. */
export function countVisible(id: string, shown: ReadonlySet<string>, hidden: ReadonlySet<string>, hasOuter: boolean) {
  if (shown.has(id)) return true;
  if (hidden.has(id)) return false;
  if (shown.has(MERGED_INNER)) return true;
  if (hidden.has(MERGED_INNER)) return false;
  return hasOuter;
}

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
 *  (a block dragged apart gets a label of its own), one per other column
 *  (a windowed table's gap columns too); null when no count column is shown. */
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

/** The total cell of an incomplete sweep (plan 20 A7): `16/20 · incomplete`
 *  and what a screen reader says for it; null for any other run. */
export function innerTotal(r: ExperimentRow): { text: string; label: string } | null {
  const text = sweepIncompleteLabel(r);
  if (!text) return null;
  const total = fleetCounts(r)?.total ?? 0;
  return { text, label: `${total} inner run${total === 1 ? "" : "s"}, ${sweepIncompleteSpoken(r)}` };
}
