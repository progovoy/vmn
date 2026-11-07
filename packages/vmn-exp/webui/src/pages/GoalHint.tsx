/** Under a board (plan 32): its metric columns without a declared goal rank
 *  nothing and sort low first, so one muted line says how to declare one —
 *  and another counts the metrics whose runs declare different goals. */
import { Link } from "react-router-dom";
import type { MetricsSchema } from "../types";
import { goalsDiffer, metricGoal, plural } from "../util";

const has = (n: number) => (n === 1 ? "has" : "have");

/** `loss (min: 2 runs, max: 1 run)`. */
function conflictTitle(schema: MetricsSchema | null, name: string) {
  const goals = Object.entries(schema?.[name]?.goals ?? {});
  return goals.length ? `${name} (${goals.map(([g, n]) => `${g}: ${plural(n ?? 0, "run")}`).join(", ")})` : name;
}

export default function GoalHint({ metrics, schema, base }: {
  /** The board's visible metric columns. */
  metrics: readonly string[];
  schema: MetricsSchema | null;
  /** The app's base path (`/ws/<ws>/app/<tag>`). */
  base: string;
}) {
  const goalLess = metrics.filter((m) => !metricGoal(schema, m));
  const differ = goalLess.filter((m) => goalsDiffer(schema, m));
  const none = goalLess.filter((m) => !differ.includes(m));
  return (
    <>
      {none.length > 0 && (
        <p className="goal-hint muted" role="note" title={`No goal: ${none.join(", ")}`}>
          {plural(none.length, "metric")} {has(none.length)} no goal — declare{" "}
          <code>goal: min|max</code> in conf.yml or the <Link to={`${base}/settings`}>app settings</Link>
        </p>
      )}
      {differ.length > 0 && (
        <p className="goal-hint muted" role="note"
           title={`Goals differ: ${differ.map((m) => conflictTitle(schema, m)).join(", ")}`}>
          {plural(differ.length, "metric")} {has(differ.length)} conflicting goals — declare one in conf.yml
        </p>
      )}
    </>
  );
}
