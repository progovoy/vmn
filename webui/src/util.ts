export function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
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

export function seriesColor(names: string[], name: string): string {
  const idx = [...names].sort().indexOf(name);
  return SERIES_VARS[Math.min(idx, SERIES_VARS.length - 1)];
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
