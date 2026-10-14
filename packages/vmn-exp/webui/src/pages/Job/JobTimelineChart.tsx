/** Progress over time (plan 23 §3.2): a stacked area of the job's runs by
 *  state per time bucket (succeeded and failed cumulative, running between
 *  them), and below it, on its own axis, completions per minute (a trailing
 *  average on a long timeline) — where a stall or a failure storm shows. Status colours from the CSS tokens,
 *  legend in words, a per-bucket tooltip. */
import type { JobTimeline } from "../../apiJob";
import { fmtCount } from "../../util";
import { round2, timelineSeries, type TimelineSeries } from "./jobData";

const W = 600;
const AREA_H = 140;
const RATE_H = 48;

/** Bottom to top: failures on the baseline, where a storm shows, the
 *  running band on top; the legend reads top to bottom. */
const LAYERS = [
  { key: "failed", tone: "failed" },
  { key: "succeeded", tone: "done" },
  { key: "running", tone: "running" },
] as const;
const LEGEND = [...LAYERS].reverse();

type X = (ms: number) => number;

const timeText = (ms: number) =>
  new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Step edges: each bucket spans [t, t + bucket). */
function edges(s: TimelineSeries, bucketMs: number) {
  const lo = s.t[0];
  const hi = s.t[s.t.length - 1] + bucketMs;
  const x = (ms: number) => ((ms - lo) / (hi - lo || 1)) * W;
  return { lo, hi, x };
}

function stackPaths(s: TimelineSeries, bucketMs: number, x: X) {
  const totals = s.t.map((_, i) => s.succeeded[i] + s.failed[i] + s.running[i]);
  const max = Math.max(1, ...totals);
  const y = (v: number) => AREA_H - (v / max) * AREA_H;
  const base = s.t.map(() => 0);
  const paths = LAYERS.map(({ key, tone }) => {
    const top = s.t.map((_, i) => base[i] + s[key][i]);
    const step = (ys: number[]) => s.t.flatMap((t, i) => [`${x(t)},${y(ys[i])}`, `${x(t + bucketMs)},${y(ys[i])}`]);
    const outline = [...step(top), ...step(base).reverse()];
    top.forEach((v, i) => { base[i] = v; });
    return { tone, d: `M${outline.join("L")}Z` };
  });
  return { paths, max };
}

/** A step line over the same bucket edges as the area, so both charts read
 *  on one x axis. */
function ratePath(s: TimelineSeries, bucketMs: number, x: X) {
  const max = Math.max(1e-9, ...s.perMinAvg);
  const y = (v: number) => RATE_H - (v / max) * (RATE_H - 4) - 2;
  const points = s.t.flatMap((t, i) => [`${x(t)},${y(s.perMinAvg[i])}`, `${x(t + bucketMs)},${y(s.perMinAvg[i])}`]);
  return { d: `M${points.join("L")}`, max };
}

/** `24-min average` (`2-h` past two hours); null for a one-bucket window. */
function averageText(s: TimelineSeries, bucketMs: number): string | null {
  if (s.rateWindow <= 1) return null;
  const minutes = (s.rateWindow * bucketMs) / 60_000;
  return `${minutes < 120 ? `${round2(minutes)}-min` : `${round2(minutes / 60)}-h`} average`;
}

/** The run-count axis: the top, a round middle when it differs, and 0. */
function countTicks(max: number): number[] {
  const mid = Math.round(max / 2);
  return mid > 0 && mid < max ? [max, mid, 0] : [max, 0];
}

/** Tick labels beside a plot, each at its value's height (top = *max*). */
function YAxis({ className, ticks, max }: { className: string; ticks: number[]; max: number }) {
  return (
    <div className={`job-axis-y ${className}`} aria-hidden="true">
      {ticks.map((v, i) => (
        <span key={v} className={`job-tick${i === 0 ? " job-axis-max" : ""}`}
          style={{ top: `${100 - (v / (max || 1)) * 100}%` }}>{fmtCount(v)}</span>
      ))}
    </div>
  );
}

function bucketTitle(s: TimelineSeries, i: number) {
  return `${timeText(s.t[i])}: ${fmtCount(s.running[i])} running, ${fmtCount(s.succeeded[i])} succeeded, `
    + `${fmtCount(s.failed[i])} failed, ${round2(s.perMin[i])} completions/min`;
}

export default function JobTimelineChart({ timeline }: { timeline: JobTimeline }) {
  if (!timeline.buckets.length) return <p className="muted job-empty">No run has started yet.</p>;
  const s = timelineSeries(timeline);
  const bucketMs = timeline.bucket_sec * 1000;
  const last = s.t.length - 1;
  const started = s.running[last] + s.succeeded[last] + s.failed[last];
  const { lo, hi, x } = edges(s, bucketMs);
  const { paths, max } = stackPaths(s, bucketMs, x);
  const rate = ratePath(s, bucketMs, x);
  const summary = `Progress over time: ${fmtCount(started)} started, ${fmtCount(s.succeeded[last])} succeeded, `
    + `${fmtCount(s.failed[last])} failed, ${fmtCount(s.running[last])} running`;
  const rateNow = round2(s.perMinAvg[last]);
  const average = averageText(s, bucketMs);
  return (
    <div className="job-timeline">
      <ul className="job-legend" aria-label="Status legend">
        {LEGEND.map(({ key, tone }) => (
          <li key={key}><span className={`job-swatch tone-${tone}`} aria-hidden="true" />{key}</li>
        ))}
      </ul>
      <div className="job-axis-unit" aria-hidden="true">runs</div>
      <div className="job-plot">
        <YAxis className="job-axis-runs" ticks={countTicks(max)} max={max} />
        <div className="job-chart-frame">
          <svg className="job-area" viewBox={`0 0 ${W} ${AREA_H}`} preserveAspectRatio="none" role="img" aria-label={summary}>
            {countTicks(max).map((v) => (
              <line key={v} className="job-grid" x1={0} x2={W} y1={AREA_H - (v / max) * AREA_H} y2={AREA_H - (v / max) * AREA_H}
                vectorEffect="non-scaling-stroke" />
            ))}
            {paths.map((p) => <path key={p.tone} d={p.d} className={`job-fill tone-${p.tone}`} />)}
            {s.t.map((t, i) => (
              <rect key={t} className="job-hit" x={x(t)} y={0} width={x(t + bucketMs) - x(t)} height={AREA_H}>
                <title>{bucketTitle(s, i)}</title>
              </rect>
            ))}
          </svg>
        </div>
      </div>
      <div className="job-chart-caption">
        completions per minute <span className="mono">({average && `${average}, `}peak {round2(rate.max)})</span>
      </div>
      <div className="job-axis-unit" aria-hidden="true">per min</div>
      <div className="job-plot">
        <YAxis className="job-axis-rate" ticks={[round2(rate.max), 0]} max={rate.max} />
        <svg className="job-rate" viewBox={`0 0 ${W} ${RATE_H}`} preserveAspectRatio="none" role="img"
          aria-label={`Completions per minute${average ? ` (${average})` : ""}: latest ${rateNow}`}>
          <path d={rate.d} className="job-rate-line" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
      <div className="job-axis-x" aria-hidden="true"><span>{timeText(lo)}</span><span>{timeText(hi)}</span></div>
    </div>
  );
}
