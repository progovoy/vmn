/** `outer · 5 runs`: marks an outer run, linked to its page when *to* is
 *  given (plain text on the outer run's own page). */
import { Link } from "react-router-dom";
import { outerLabel } from "../util/outerRun";

export default function OuterBadge({ count, to }: { count: number | null; to?: string }) {
  const text = outerLabel(count);
  if (!to) return <span className="badge outer-badge">{text}</span>;
  return (
    <Link className="badge outer-badge" to={to} title="an outer run: open its page" onClick={(e) => e.stopPropagation()}>
      {text}
    </Link>
  );
}
