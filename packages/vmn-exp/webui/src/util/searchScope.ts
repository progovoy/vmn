/** Search across every run (plan 23 W11, §3.5): the links that carry one
 *  filter between the Jobs view, a job's Runs tab and All runs, and the
 *  Jobs view's result line. */
import { fmtCount, plural, runHref } from "../util";

export interface SearchFilter {
  query?: string;
  search?: string;
  branch?: string;
  archived?: boolean;
}

function filterParams(f: SearchFilter, p = new URLSearchParams()): URLSearchParams {
  for (const [k, v] of [["q", f.query], ["search", f.search], ["branch", f.branch]] as const) {
    if (v?.trim()) p.set(k, v);
  }
  if (f.archived) p.set("archived", "1");
  return p;
}

/** A job's Runs tab with *f* applied (its `N matching runs` chip). */
export const matchingRunsHref = (runBase: string, verstr: string, f: SearchFilter) =>
  `${runHref(runBase, verstr)}?${filterParams(f, new URLSearchParams({ tab: "runs" }))}`;

/** All runs of the app with *f* applied, no job scope. */
export const allRunsHref = (appBase: string, f: SearchFilter) =>
  `${appBase}?${filterParams(f, new URLSearchParams({ view: "all" }))}`;

/** Text or a query: what makes the Jobs view search every run. */
export const hasSearch = (f: SearchFilter) => Boolean(f.query?.trim() || f.search?.trim());

/** `3 jobs · 412 runs match` and the switch to All runs. */
export function matchLine(jobs: number, runs: number): { found: string; all: string | null } {
  if (!runs) return { found: "no runs match", all: null };
  return {
    found: `${plural(jobs, "job")} · ${plural(runs, "run")} match${runs === 1 ? "es" : ""}`,
    all: runs === 1 ? "show the 1 run" : `show all ${fmtCount(runs)} runs`,
  };
}
