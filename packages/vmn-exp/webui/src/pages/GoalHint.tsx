/** Under a board (plan 32): its metric columns without a declared goal rank
 *  nothing and sort low first, so one muted line says how to declare one. */
import { Link } from "react-router-dom";
import type { MetricsSchema } from "../types";
import { metricGoal, plural } from "../util";

export default function GoalHint({ metrics, schema, base }: {
  /** The board's visible metric columns. */
  metrics: readonly string[];
  schema: MetricsSchema | null;
  /** The app's base path (`/ws/<ws>/app/<tag>`). */
  base: string;
}) {
  const goalLess = metrics.filter((m) => !metricGoal(schema, m));
  if (!goalLess.length) return null;
  return (
    <p className="goal-hint muted" role="note" title={`No goal: ${goalLess.join(", ")}`}>
      {plural(goalLess.length, "metric")} {goalLess.length === 1 ? "has" : "have"} no goal — declare{" "}
      <code>goal: min|max</code> in conf.yml or the <Link to={`${base}/settings`}>app settings</Link>
    </p>
  );
}
