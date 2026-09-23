/** The one seconds ladder: 42s / 7m / 2h / 3d. Always floors, so nothing ever
 *  claims a threshold it has not reached. */
export function humanizeSeconds(secs: number): string {
  if (secs < 60) return `${Math.floor(secs)}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h`;
  return `${Math.floor(secs / 86400)}d`;
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  return `${humanizeSeconds(Math.max(0, (Date.now() - then) / 1000))} ago`;
}

export function fmtVal(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") {
    return Math.abs(v) >= 1000 || (v !== 0 && Math.abs(v) < 0.001)
      ? v.toExponential(3)
      : String(Math.round(v * 10000) / 10000);
  }
  return String(v);
}


/** Compact duration for run status labels, on the same ladder as `relTime`. */
export function fmtDuration(secs: number | null | undefined): string {
  if (secs == null) return "—";
  return humanizeSeconds(secs);
}

/** Refresh cadence for a still-unfinished run. Status only moves at the
 *  heartbeat, so polling faster than half of it just repeats the answer. */
export function pollIntervalMs(heartbeatSec: number | null | undefined): number {
  if (heartbeatSec == null) return 15000;
  return Math.max(5000, Math.round((heartbeatSec * 1000) / 2));
}

/** Copy to clipboard, falling back to execCommand where the async
 *  clipboard API is unavailable (plain-http hosts) or denied. */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard) {
    const ok = await navigator.clipboard
      .writeText(text)
      .then(() => true, () => false);
    if (ok) return true;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  return ok;
}

/** Fixed categorical assignment (never cycled): metric name -> series slot.
 *  Order matches the redesign: loss -> --minor (blue), val_loss -> --hotfix. */
const SERIES_VARS = [
  "var(--minor)", "var(--hotfix)", "var(--patch)",
  "var(--pre)", "var(--major)", "var(--series-4)",
];

/** Colour for the i-th series: the six design-system slots first, then
 *  golden-angle HSL hues so any number of runs stay distinguishable. */
export function runColor(i: number): string {
  if (i < SERIES_VARS.length) return SERIES_VARS[Math.max(0, i)];
  const hue = Math.round(((i - SERIES_VARS.length) * 137.508) % 360);
  const light = 55 + ((i - SERIES_VARS.length) % 3) * 8;
  return `hsl(${hue}, 65%, ${light}%)`;
}

export function seriesColor(names: string[], name: string): string {
  return runColor([...names].sort().indexOf(name));
}

/** A run's param value: the verbatim `params` dict is the source of truth;
 *  `user_meta` (snapshot `--meta`) is only a fallback for older rows. */
export function paramValue(
  row: { params?: Record<string, unknown> | null; user_meta?: Record<string, unknown> | null },
  key: string,
): unknown {
  if (row.params && key in row.params) return row.params[key];
  return row.user_meta?.[key];
}

/** Loss/error-like metric names improve downward (Keras mode="auto"). */
const MIN_LIKE = /(^|_)(loss|err|error|mae|mse|rmse|perplexity|ppl)($|_|\d)/i;

/** Display goal for a metric — used for best-value highlights, bar direction,
 *  and delta coloring (never for ordering, which stays server-side). A schema
 *  entry wins; otherwise the goal is inferred from the metric's name, falling
 *  back to higher-is-better. */
export function metricGoal(
  schema: Record<string, { goal?: string }> | null, key: string
): "min" | "max" {
  const spec = schema?.[key];
  if (spec) return spec.goal === "min" ? "min" : "max";
  return MIN_LIKE.test(key) ? "min" : "max";
}
