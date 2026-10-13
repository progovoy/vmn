/** A sweep that ran fewer trials than it planned (plan 20 D12): every trial
 *  finished, yet its tree is `created` because trials are still to come. */
import type { RunStatus } from "../types";

type SweepFields = Partial<RunStatus>;

/** `16/20 · incomplete` for such a sweep, else null. */
export function sweepIncompleteLabel(st: SweepFields): string | null {
  const planned = st.sweep_planned;
  const trials = st.sweep_trials ?? 0;
  if (planned == null || st.tree_status !== "created" || trials >= planned) return null;
  return `${trials}/${planned} · incomplete`;
}

/** What a screen reader says for it: `16 of 20 planned trials, incomplete`. */
export function sweepIncompleteSpoken(st: SweepFields): string | null {
  if (!sweepIncompleteLabel(st)) return null;
  return `${st.sweep_trials ?? 0} of ${st.sweep_planned} planned trials, incomplete`;
}
