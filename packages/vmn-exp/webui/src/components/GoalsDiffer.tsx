import type { DiffDelta } from "../types";

/** A metric delta whose two runs declare different goals has no verdict
 *  (plan 32 F9): this says so next to its name, naming both goals. */
export default function GoalsDiffer({ delta }: { delta: DiffDelta }) {
  if (!delta.goal_conflict) return null;
  return (
    <span className="muted" title={`the runs declare ${delta.goals?.join(" vs ")}`}>
      {" "}goals differ
    </span>
  );
}
