/** How fresh the data an app's index serves is (experiments-status
 *  `freshness`, ui/freshness.py), and what the dashboard says about it: a
 *  banner while the data is older than `stale_after_sec` (a sync's progress,
 *  or an error when the refresh does not complete), nothing once a refresh
 *  published fresh data. */

export interface Freshness {
  /** ISO wall time of the data (the last completed refresh's start); null before one. */
  as_of: string | null;
  refreshing: boolean;
  refresh_running_sec: number | null;
  phase: "full_listing" | "journal" | "listing" | "loading_new" | "idle";
  progress: number | null;
  /** Failing, gone, or running past the server's timeout. */
  refresh_failing: boolean;
  last_error: string | null;
  stale_after_sec: number;
}

import { fmtPct, humanizeSeconds } from "../util";

export interface FreshnessBanner { kind: "stale" | "error"; text: string }

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PHASES: Record<Freshness["phase"], string> = {
  full_listing: "listing runs", listing: "listing runs",
  journal: "reading the change journal", loading_new: "loading new runs", idle: "",
};

const pad = (n: number) => String(n).padStart(2, "0");

/** `Oct 22 19:44 UTC` */
function asOfText(ms: number): string {
  const d = new Date(ms);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

const ageSec = (f: Freshness, now: number) =>
  f.as_of === null ? null : (now - Date.parse(f.as_of)) / 1000;

const isOld = (f: Freshness, now: number) => {
  const age = ageSec(f, now);
  return age !== null && age > f.stale_after_sec;
};

/** Whether a refresh runs on data past the threshold (poll fast meanwhile). */
export const refreshingOnOldData = (f: Freshness | undefined, now = Date.now()) =>
  Boolean(f?.refreshing && isOld(f, now));

const ageText = (sec: number) => humanizeSeconds(Math.max(sec, 0));
const percent = (p: number | null) => (p === null ? "" : `~${fmtPct(p * 100)}`);
const lastError = (f: Freshness) => (f.last_error ? ` (last error: ${f.last_error})` : "");

export function freshnessBanner(f: Freshness | undefined, now = Date.now()): FreshnessBanner | null {
  if (!f) return null;
  const age = ageSec(f, now);
  if (age === null) {
    return f.refresh_failing
      ? { kind: "error", text: `⚠ The background refresh has not completed${lastError(f)}.` }
      : null;
  }
  if (age <= f.stale_after_sec) return null;
  if (f.refresh_failing) {
    const stalled = ageText(f.refresh_running_sec ?? age);
    return { kind: "error", text: `⚠ Data is ${ageText(age)} old and the background refresh `
      + `has not completed for ${stalled}${lastError(f)}.` };
  }
  const shown = `⚠ Showing data as of ${asOfText(Date.parse(f.as_of!))} (${ageText(age)} old).`;
  if (!f.refreshing) return { kind: "stale", text: shown };
  const doing = PHASES[f.phase] || "refreshing";
  return { kind: "stale", text: `${shown} Syncing with the store — ${doing}`
    + `${f.progress === null ? "" : `, ${percent(f.progress)}`}. New runs will appear when it finishes.` };
}

/** The boards' count-line form: `data 4 d old · syncing ~45%`; "" while fresh. */
export function freshnessShort(f: Freshness | undefined, now = Date.now()): string {
  if (!f || !isOld(f, now)) return "";
  const old = `data ${ageText(ageSec(f, now)!)} old`;
  if (f.refresh_failing) return `${old} · refresh not completing`;
  if (!f.refreshing) return old;
  return `${old} · syncing ${percent(f.progress)}`.trimEnd();
}
