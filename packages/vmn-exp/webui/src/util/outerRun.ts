/** What marks an outer run (`kind = "outer"`, a run with inner runs) and how
 *  many runs its subtree holds, from whatever the row already carries. */
import type { ExperimentRow } from "../types";
import { plural } from "../util";

type OuterFields = Partial<Pick<ExperimentRow, "kind" | "job" | "children" | "fleet">>;

export const isOuterRun = (r: OuterFields) => r.kind === "outer" || !!r.job || !!r.children?.length;

/** The subtree's runs: the rollup's total, else the fleet's counts, else the
 *  direct inner runs; null when the row carries none of them. */
export function outerRunCount(r: OuterFields): number | null {
  if (r.job) return r.job.total;
  if (r.fleet) return Object.values(r.fleet.counts).reduce((n, c) => n + c, 0);
  return r.children?.length ? r.children.length : null;
}

/** `outer · 5 runs`, `outer` without a count. */
export const outerLabel = (count: number | null) => (count == null ? "outer" : `outer · ${plural(count, "run")}`);
