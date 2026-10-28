/** What the job page derives from a job's summary and failures (plan 23
 *  W2, W5): the timeline's series, the KPI tiles, and the words and commands
 *  around them. Pure. */
import type { FailureCluster, JobMetric, JobPageSummary, JobTimeline, TimelineBucket } from "../../apiJob";
import { vmnExpCommand } from "../../shell/cliCommands";
import { fmtCount, fmtDuration, fmtParam, fmtPct, fmtVal, plural } from "../../util";
import { eqClause } from "../../util/searchQuery";

const toMs = (t: number | string) => (typeof t === "number" ? t * 1000 : Date.parse(t));

export interface TimelineSeries {
  /** Bucket starts, ms since the epoch. */
  t: number[];
  running: number[];
  /** Cumulative. */
  succeeded: number[];
  /** Cumulative. */
  failed: number[];
  /** Completions per minute in each bucket. */
  perMin: number[];
  /** Runs released per minute in each bucket (an eviction wave shows here). */
  released: number[];
  /** `perMin`'s trailing average over `rateWindow` buckets: what the chart plots. */
  perMinAvg: number[];
  rateWindow: number;
}

/** Buckets a rate's trailing average spans: ~1/120 of the timeline, at least one. */
const RATE_POINTS = 120;

function trailingMean(values: number[], window: number): number[] {
  let sum = 0;
  return values.map((v, i) => {
    sum += v - (i >= window ? values[i - window] : 0);
    return sum / Math.min(i + 1, window);
  });
}

/** The server's buckets are sparse (only those something happened in):
 *  every bucket from the first to the last, the empty ones zero. */
function denseBuckets({ bucket_sec: size, buckets }: JobTimeline) {
  const step = size * 1000;
  const at = new Map(buckets.map((b) => [toMs(b.t), b]));
  const out: (Required<Omit<TimelineBucket, "t">> & { t: number })[] = [];
  if (!buckets.length || step <= 0) return out;
  const last = toMs(buckets[buckets.length - 1].t);
  for (let ms = toMs(buckets[0].t); ms <= last; ms += step) {
    const b = at.get(ms);
    out.push({
      t: ms / 1000, started: b?.started ?? 0, succeeded: b?.succeeded ?? 0, failed: b?.failed ?? 0,
      released: b?.released ?? 0,
    });
  }
  return out;
}

/** The stacked area's series: running(t) = cumulative started - cumulative
 *  ended, the finished ones cumulative; plus completions per minute, raw
 *  and as a trailing average (2 days of minutes would be noise). */
export function timelineSeries(timeline: JobTimeline): TimelineSeries {
  const out: TimelineSeries = {
    t: [], running: [], succeeded: [], failed: [], perMin: [], released: [], perMinAvg: [], rateWindow: 1,
  };
  const minutes = timeline.bucket_sec / 60;
  let started = 0, succeeded = 0, failed = 0;
  for (const b of denseBuckets(timeline)) {
    started += b.started;
    succeeded += b.succeeded;
    failed += b.failed;
    out.t.push(toMs(b.t));
    out.running.push(Math.max(started - succeeded - failed, 0));
    out.succeeded.push(succeeded);
    out.failed.push(failed);
    out.perMin.push(minutes > 0 ? (b.succeeded + b.failed) / minutes : 0);
    out.released.push(minutes > 0 ? b.released / minutes : 0);
  }
  out.rateWindow = Math.max(1, Math.round(out.t.length / RATE_POINTS));
  out.perMinAvg = trailingMean(out.perMin, out.rateWindow);
  return out;
}

/** The runs the failure clusters cover: failed, stuck and lost. */
export const failedCount = (s: Pick<JobPageSummary, "counts" | "lost">) =>
  s.counts.failed + s.counts.stuck + (s.lost ?? 0);

/** The main metric: the server's, else the first tracked one with values. */
export function mainMetric(s: JobPageSummary): string | null {
  if (s.metric && s.metrics[s.metric]) return s.metric;
  return Object.keys(s.metrics).find((m) => s.metrics[m]) ?? null;
}

export interface KpiTile {
  label: string;
  value: string;
  sub?: string;
  /** A run's verstr the tile links to. */
  href?: string;
  tone?: "running" | "waiting" | "stuck" | "failed" | "done";
}

export function jobKpis(s: JobPageSummary): KpiTile[] {
  const tiles: KpiTile[] = [
    { label: "done", value: fmtCount(s.done), sub: `of ${fmtCount(s.expected)}`, tone: "done" },
    {
      label: "failed", value: fmtPct(s.failed_pct), tone: "failed",
      sub: plural(s.counts.failed + (s.lost ?? 0), "run"),
    },
    { label: "running", value: fmtCount(s.counts.running), tone: "running" },
    { label: "waiting", value: fmtCount(s.counts.waiting), tone: "waiting" },
    { label: "stuck", value: fmtCount(s.counts.stuck), tone: "stuck" },
    { label: "median duration", value: fmtDuration(s.duration.p50) },
    { label: "p90 duration", value: fmtDuration(s.duration.p90) },
  ];
  const metric = mainMetric(s);
  const m = metric ? s.metrics[metric] : null;
  if (metric && m && s.ranked !== false) tiles.push({ label: `best ${metric}`, value: fmtVal(m.best), href: m.best_verstr });
  return tiles;
}

export const round2 = (n: number) => Math.round(n * 100) / 100;

/** The query clause selecting a failure cluster's runs; null for a
 *  signature holding both quotes (the language has no escapes). */
export const failureQuery = (sig: string): string | null => eqClause("failure_sig", sig);

/** A share (0..1) in whole percent. */
export const sharePct = (share: number) => Math.round(share * 100);
const pct = (share: number) => fmtPct(share * 100);

/** `batch_size = 512 · 94% vs 25%`: in the cluster vs in the job. */
export const paramShareText = (p: FailureCluster["params"][number]) =>
  `${p.key} = ${fmtParam(p.value)} · ${pct(p.share)} vs ${pct(p.base_share)}`;

export const rerunCommand = (appName: string, verstr: string, storeUri?: string) =>
  vmnExpCommand(["rerun", appName, "-v", verstr], storeUri);

/** p10/p50/p90 as fractions along the histogram's [min, max]. */
export function quantileMarks(m: JobMetric): { label: string; value: number; at: number }[] {
  const span = m.max - m.min;
  return (["p10", "p50", "p90"] as const).flatMap((label) => {
    const value = m[label];
    if (value == null) return [];
    const at = span > 0 ? Math.min(Math.max((value - m.min) / span, 0), 1) : 0.5;
    return [{ label, value, at }];
  });
}
