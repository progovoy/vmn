/** Foldable outer runs: every outer starts shut; `expand=` opens it and its
 *  inner runs are listed right under it. */
import type { ExperimentRow } from "../types";

/** A table row standing in for inner runs not on screen yet: loading, failed
 *  to load, or *count* more than the fetched page holds. */
export interface PendingRow {
  pending: true;
  key: string;
  parent: string;
  depth: number;
  state: "loading" | "error" | "more";
  count?: number;
}
export type TableItem = ExperimentRow | PendingRow;

export const isPending = (r: TableItem): r is PendingRow => (r as PendingRow).pending === true;

/** An open outer's inner runs (with how many the page left out), or why
 *  they are not there yet. */
export type InnerRuns = { rows: ExperimentRow[]; more: number } | "loading" | "error";

/** Whether an outer run is shut; null for a run without inner runs. */
export function foldState(r: ExperimentRow, expanded: ReadonlySet<string>): boolean | null {
  return r.children?.length ? !expanded.has(r.verstr) : null;
}

/** *top* with every open outer's inner runs (from *innerOf*, filtered by
 *  *keep*) under it, depth-first; a placeholder where they are not loaded. */
export function treeRows(
  top: readonly ExperimentRow[], expanded: ReadonlySet<string>,
  innerOf: (outer: ExperimentRow) => InnerRuns, keep: (r: ExperimentRow) => boolean = () => true,
): TableItem[] {
  const out: TableItem[] = [];
  const seen = new Set<string>();
  const pending = (r: ExperimentRow, state: PendingRow["state"], count?: number) => out.push({
    pending: true, key: `${r.verstr}::${state}`, parent: r.verstr, depth: (r.depth ?? 0) + 1, state, count,
  });
  const visit = (r: ExperimentRow) => {
    if (seen.has(r.verstr)) return;
    seen.add(r.verstr);
    out.push(r);
    if (foldState(r, expanded) !== false) return;
    const inner = innerOf(r);
    if (typeof inner === "string") {
      pending(r, inner);
      return;
    }
    inner.rows.filter(keep).forEach(visit);
    if (inner.more > 0) pending(r, "more", inner.more);
  };
  top.forEach(visit);
  return out;
}
