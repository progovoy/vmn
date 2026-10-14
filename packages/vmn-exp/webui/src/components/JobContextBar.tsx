/** An inner run's job context bar (plan 23 W7, §3.3), under the run header:
 *  `Job lr_layers_grid › run 1,903 of 2,000 · rank 1 of 1,409 on val_loss ·
 *  ‹ prev  next ›`, with the run's value marked on the job's distribution.
 *  `[` and `]` go to the previous and next run. */
import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { JobMetric } from "../apiJob";
import { useJobContext } from "../hooks/useJobContext";
import { jobTabHref } from "../pages/Job/jobQueries";
import { fmtCount, fmtVal, runHref } from "../util";
import { histMarkAt, runContextSearch } from "../util/runContext";
import "./JobContextBar.css";

const W = 120;
const H = 24;

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

/** The job's histogram of *metric*, *value* marked. */
function PeersMark({ metric, m, value }: { metric: string; m: JobMetric; value: number }) {
  const at = histMarkAt(m.hist, value);
  const top = Math.max(1, ...m.hist.map((b) => b.count));
  const w = W / Math.max(m.hist.length, 1);
  return (
    <svg className="job-context-peers" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
      aria-label={`${metric} ${fmtVal(value)} among ${fmtCount(m.n)} runs of the job`}>
      {m.hist.map((b, i) => {
        const h = (b.count / top) * (H - 2);
        return <rect key={i} className="job-context-bin" x={i * w + 0.5} y={H - h} width={Math.max(w - 1, 1)} height={h} />;
      })}
      {at !== null && <line className="job-context-mark" x1={at * W} x2={at * W} y1={0} y2={H} />}
    </svg>
  );
}

export default function JobContextBar({ ws, app, verstr, idx, job, metrics }: {
  ws: string; app: string; verstr: string; idx: number | null;
  /** The parent job's verstr. */
  job: string;
  metrics: Record<string, number | string | null>;
}) {
  const navigate = useNavigate();
  const ctx = useJobContext({ ws, app, verstr, idx, job, metrics });
  const base = `/ws/${ws}/app/${app}`;
  const hrefOf = (n: { row: { verstr: string }; at: number } | null) =>
    n && `${runHref(base, n.row.verstr)}${runContextSearch(ctx.order, n.at)}`;
  const prev = hrefOf(ctx.prev);
  const next = hrefOf(ctx.next);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target)) return;
      const to = e.key === "[" ? prev : e.key === "]" ? next : null;
      if (!to) return;
      e.preventDefault();
      navigate(to);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prev, next, navigate]);

  // Nothing until the job's rollup lands (none from a server without it).
  if (!ctx.summary) return null;
  const name = ctx.summary.name || job;
  return (
    <nav className="job-context" aria-label="Job context">
      <span>Job <Link className={ctx.summary.name ? undefined : "mono"} to={jobTabHref(runHref(base, job), "runs")}>{name}</Link></span>
      {ctx.place && <><span aria-hidden="true">›</span><span>{`run ${fmtCount(ctx.place.at + 1)} of ${fmtCount(ctx.place.total)}`}</span></>}
      {ctx.rank && (
        <span>{`· rank ${fmtCount(ctx.rank.rank)} of ${fmtCount(ctx.rank.of)} on ${ctx.rank.metric}`}</span>
      )}
      {ctx.peers && <PeersMark {...ctx.peers} />}
      {(prev || next) && (
        <span className="job-context-nav">
          {prev ? <Link to={prev} title="Previous run ([)" aria-keyshortcuts="[">‹ prev</Link> : <span className="muted">‹ prev</span>}
          {next ? <Link to={next} title="Next run (])" aria-keyshortcuts="]">next ›</Link> : <span className="muted">next ›</span>}
        </span>
      )}
    </nav>
  );
}
