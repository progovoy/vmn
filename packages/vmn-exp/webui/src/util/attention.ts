/** The attention strip's parts (plan 20 C6): what needs a look now, each with
 *  the leaderboard search that lists exactly those runs. */
import type { AppStatus } from "../shell/contracts";

/** experiments-status counts failures this far back (status_summary.py). */
const RECENT_MS = 24 * 3600 * 1000;
/** The board's filters: following a part replaces them all. */
const FILTER_PARAMS = ["q", "status", "search", "branch", "archived", "sel", "offset"];

export interface AttentionPart { key: "stuck" | "failed" | "running"; text: string; search: string; title?: string }

/** `finished_at >= "<24h before now>"`, second precision like the stored stamps. */
export function recentClause(now: number): string {
  return `finished_at >= "${new Date(now - RECENT_MS).toISOString().replace(/\.\d+Z$/, "Z")}"`;
}

function withFilter(current: string, set: Record<string, string>): string {
  const p = new URLSearchParams(current);
  for (const k of FILTER_PARAMS) p.delete(k);
  for (const [k, v] of Object.entries(set)) p.set(k, v);
  return `?${p.toString()}`;
}

/** Nothing when no run is stuck and none failed in the last 24h: running
 *  runs alone need no attention. *current* is the board's search. */
export function attentionParts(status: AppStatus, current: string, now: number): AttentionPart[] {
  const { counts, failed_recent } = status;
  if (!counts.stuck && !failed_recent) return [];
  const parts: AttentionPart[] = [];
  if (counts.stuck) {
    parts.push({ key: "stuck", text: `${counts.stuck} stuck`, search: withFilter(current, { status: "stuck" }) });
  }
  if (failed_recent) {
    parts.push({
      key: "failed",
      text: `${failed_recent} failed in 24h`,
      title: "failed in the last 24 h, newest first",
      search: withFilter(current, {
        status: "failed", q: recentClause(now), sort: "finished_at", order: "desc",
      }),
    });
  }
  if (counts.running) {
    parts.push({ key: "running", text: `${counts.running} running`, search: withFilter(current, { status: "running" }) });
  }
  return parts;
}
