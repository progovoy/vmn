/** The attention strip's parts (plan 20 C6): what needs a look now, each with
 *  the leaderboard search that lists exactly those runs. */
import type { AppStatus, AttentionEntry, AttentionLevel } from "../shell/contracts";

/** experiments-status counts failures this far back (status_summary.py). */
const RECENT_MS = 24 * 3600 * 1000;
/** The board's filters: following a part replaces them all. */
const FILTER_PARAMS = ["q", "status", "search", "branch", "archived", "sel", "offset"];

/** *key* is a built-in part's (stuck, failed, running) or a configured
 *  query's (plan 28 P1), which alone carries a *level*. */
export interface AttentionPart { key: string; text: string; search: string; title?: string; level?: AttentionLevel }

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

/** The board filter listing the runs `counts.stuck` counts: it leaves out
 *  the ones an ended outer run lost (status_summary.py). */
export const stuckFilter = (status: Pick<AppStatus, "lost">): Record<string, string> =>
  ({ status: "stuck", ...(status.lost ? { q: "settled = null" } : {}) });

/** A configured query's part: its runs, the board filtered by its text. */
const configuredPart = (e: AttentionEntry, current: string): AttentionPart =>
  ({ key: e.key, level: e.level, text: `${e.count} ${e.label}`, title: e.q, search: withFilter(current, { q: e.q }) });

/** Nothing when no run is stuck, none failed in the last 24h and no
 *  configured query matches: running runs alone need no attention.
 *  *current* is the search the links start from (the board's). */
export function attentionParts(status: AppStatus, current: string, now: number): AttentionPart[] {
  const { counts, failed_recent } = status;
  const configured = (status.attention ?? []).filter((e) => e.count > 0);
  if (!counts.stuck && !failed_recent && !configured.length) return [];
  const parts: AttentionPart[] = [];
  if (counts.stuck) {
    parts.push({ key: "stuck", text: `${counts.stuck} stuck`, search: withFilter(current, stuckFilter(status)) });
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
  parts.push(...configured.map((e) => configuredPart(e, current)));
  if (counts.running) {
    parts.push({ key: "running", text: `${counts.running} running`, search: withFilter(current, { status: "running" }) });
  }
  return parts;
}
