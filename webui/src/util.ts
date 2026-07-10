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

export function shortVerstr(verstr: string): string {
  // 0.0.1-dev.a1b2c3d.e4f5g6h.r2 -> 0.0.1-dev.a1b2c3d.e4f5g6h.r2 is long;
  // keep base + first hash for tables.
  const m = verstr.match(/^(.+?-dev\.[0-9a-f]{7})\.[0-9a-f]{7}(\.r\d+)?$/);
  return m ? `${m[1]}…${m[2] ?? ""}` : verstr;
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

/** Fixed categorical assignment (never cycled): metric name -> series slot. */
const SERIES_VARS = [
  "var(--series-1)", "var(--series-2)", "var(--series-3)",
  "var(--series-4)", "var(--series-5)", "var(--series-6)",
];

export function seriesColor(names: string[], name: string): string {
  const idx = [...names].sort().indexOf(name);
  return SERIES_VARS[Math.min(idx, SERIES_VARS.length - 1)];
}
