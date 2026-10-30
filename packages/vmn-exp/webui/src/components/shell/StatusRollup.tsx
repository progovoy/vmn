/** What needs attention in an app now: stuck runs, recent failures, running
 *  runs. Each number links to the leaderboard query that lists those runs —
 *  on All runs, as the counts are of every run (inner ones too), which the
 *  Outer runs view would not list. */
import { Fragment } from "react";
import { Link } from "react-router-dom";
import type { AppStatus } from "../../shell/contracts";
import { stuckFilter } from "../../util/attention";
import { partsSoFar } from "../../util/indexing";
import "./StatusRollup.css";

const RUNS = "?view=all";

interface Part { text: string; search: string; title?: string }

function partsOf(status: AppStatus): Part[] {
  const { counts, failed_recent } = status;
  const parts: Part[] = [];
  if (counts.stuck) {
    parts.push({ text: `${counts.stuck} stuck`, search: `${RUNS}&${new URLSearchParams(stuckFilter(status))}` });
  }
  if (failed_recent) {
    parts.push({
      text: `${failed_recent} failed (24h)`,
      search: `${RUNS}&status=failed&sort=finished_at&order=desc`,
      title: "failed in the last 24 h, newest first",
    });
  }
  if (counts.running) parts.push({ text: `${counts.running} running`, search: `${RUNS}&status=running` });
  return partsSoFar(parts, status);
}

/** *href* turns a leaderboard search (`?status=stuck`) into a link target.
 *  *compact* (the sidebar) wraps the parts instead of keeping one line; every
 *  link is named by exactly what it shows. */
export default function StatusRollup({ status, href, compact }: {
  status?: AppStatus | null;
  href: (search: string) => string;
  compact?: boolean;
}) {
  if (!status) return null;
  const parts = partsOf(status);
  if (!parts.length) return null;
  return (
    <span className={`status-rollup${compact ? " compact" : ""}`}>
      {status.rollup && <span className={`rollup-dot rollup-${status.rollup}`} aria-hidden="true" />}
      {parts.map((p, i) => (
        <Fragment key={p.search}>
          {i > 0 && <span className="rollup-sep" aria-hidden="true">·</span>}
          <Link to={href(p.search)} title={p.title}>
            {p.text}
          </Link>
        </Fragment>
      ))}
    </span>
  );
}
