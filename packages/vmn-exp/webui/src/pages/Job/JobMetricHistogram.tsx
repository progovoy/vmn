/** A metric's distribution over the job's runs (plan 23 §3.2): the rollup
 *  sketch's histogram, p10/p50/p90 marked, the metric choosable. */
import { useState } from "react";
import type { JobMetric } from "../../apiJob";
import { fmtCount, fmtVal } from "../../util";
import { quantileMarks } from "./jobData";

const W = 600;
const H = 120;
const GAP = 2;

function Bars({ m }: { m: JobMetric }) {
  const max = Math.max(1, ...m.hist.map((b) => b.count));
  const w = W / Math.max(m.hist.length, 1);
  return (
    <>
      {m.hist.map((b, i) => {
        const h = (b.count / max) * (H - 2);
        return (
          <rect key={i} className="job-hist-bar" x={i * w + GAP / 2} y={H - h} width={Math.max(w - GAP, 1)} height={h} rx={2}>
            <title>{`${fmtVal(b.lo)} – ${fmtVal(b.hi)}: ${fmtCount(b.count)} runs`}</title>
          </rect>
        );
      })}
    </>
  );
}

export default function JobMetricHistogram({ metrics, initial }: {
  metrics: Record<string, JobMetric | null>; initial: string | null;
}) {
  const names = Object.keys(metrics).filter((k) => metrics[k]);
  const [picked, setPicked] = useState<string | null>(null);
  const metric = [picked, initial].find((k) => k && metrics[k]) ?? names[0];
  const m = metric ? metrics[metric] : null;
  if (!metric || !m) return <p className="muted job-empty">No run in this outer run logged a metric yet.</p>;
  const marks = quantileMarks(m);
  const label = `${metric} over ${fmtCount(m.n)} runs`
    + (marks.length ? `: ${marks.map((q) => `${q.label} ${fmtVal(q.value)}`).join(", ")}` : "");
  return (
    <div className="job-hist">
      <label className="job-picker">
        metric
        <select aria-label="Distribution metric" value={metric} onChange={(e) => setPicked(e.target.value)}>
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <div className="job-chart-frame job-hist-frame">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
          <Bars m={m} />
          {marks.map((q) => (
            <line key={q.label} className={`job-q job-q-${q.label}`} x1={q.at * W} x2={q.at * W} y1={0} y2={H}
              vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {marks.map((q) => (
          <span key={q.label} className="job-q-label" style={{ left: `${q.at * 100}%` }} aria-hidden="true">
            {q.label}
          </span>
        ))}
      </div>
      <div className="job-axis-x" aria-hidden="true"><span>{fmtVal(m.min)}</span><span>{fmtVal(m.max)}</span></div>
    </div>
  );
}
