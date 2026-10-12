/** What needs attention in an app now: stuck runs, recent failures, running
 *  runs. Each number links to the leaderboard query that lists those runs. */
import { Link } from "react-router-dom";
import type { AppStatus } from "../../shell/contracts";
import "./StatusRollup.css";

interface Part { text: string; search: string; title?: string }

function partsOf({ counts, failed_recent }: AppStatus): Part[] {
  const parts: Part[] = [];
  if (counts.stuck) parts.push({ text: `${counts.stuck} stuck`, search: "?status=stuck" });
  if (failed_recent) {
    parts.push({
      text: `${failed_recent} failed (24h)`,
      search: "?status=failed&sort=finished_at&order=desc",
      title: "failed in the last 24 h, newest first",
    });
  }
  if (counts.running) parts.push({ text: `${counts.running} running`, search: "?status=running" });
  return parts;
}

/** *href* turns a leaderboard search (`?status=stuck`) into a link target.
 *  *compact* shows the dot and the first part, the full text as its name. */
export default function StatusRollup({ status, href, compact }: {
  status?: AppStatus | null;
  href: (search: string) => string;
  compact?: boolean;
}) {
  if (!status) return null;
  const parts = partsOf(status);
  if (!parts.length) return null;
  const full = parts.map((p) => p.text).join(" · ");
  const shown = compact ? parts.slice(0, 1) : parts;
  return (
    <span className={`status-rollup${compact ? " compact" : ""}`}>
      {status.rollup && <span className={`rollup-dot rollup-${status.rollup}`} aria-hidden="true" />}
      {shown.map((p, i) => (
        <span key={p.search}>
          {i > 0 && " · "}
          <Link to={href(p.search)} title={p.title} aria-label={compact ? full : undefined}>
            {p.text}
          </Link>
        </span>
      ))}
    </span>
  );
}
