/** The Outer runs view's status chips: an outer run matches a status by its
 *  tree, not its own status — a launch run ends once it has submitted its
 *  runs, and a failed run anywhere makes its tree_status read failed while
 *  the rest still run. Running and stuck match the outer run or any run
 *  below it (`running_below`, `stuck_below`, its rollup's counts); the
 *  ended states and created match its tree_status; failed with a failure
 *  share N (plan 31 §1) matches the trees failing at least N% instead
 *  (`failed_pct`). The lost chip (plan 34 §3) adds the trees with lost runs
 *  below them (`lost_below`). Sent as `top_q`, beside the preset's query. */
import type { RunState } from "../../types";
import { inDisplayOrder } from "../../util/filterTokens";

const TREE_CLAUSES: Record<RunState, string> = {
  running: 'status = "running" or running_below > 0',
  stuck: 'status = "stuck" or stuck_below > 0',
  failed: 'tree_status = "failed"',
  succeeded: 'tree_status = "succeeded"',
  created: 'tree_status = "created"',
};

/** The `?status=` CSV as a query over the outer runs' trees ("" for none),
 *  failed by *failedPct* (`?failed_pct=`) when given, and the trees with
 *  lost runs when *lost* (`?lost=1`). */
export function treeStatusQuery(csv: string, failedPct?: number | null, lost = false): string {
  const clause = (s: RunState) => (s === "failed" && failedPct != null ? `failed_pct >= ${failedPct}` : TREE_CLAUSES[s]);
  const clauses = inDisplayOrder(csv.split(",")).map(clause);
  return (lost ? [...clauses, "lost_below > 0"] : clauses).join(" or ");
}
