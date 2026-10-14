/** The app-wide run selection: one list of picks per (workspace, app) in
 *  sessionStorage, so the picks follow the user across the Jobs view, job
 *  pages and All runs, and the tray on every page shows them. */
import type { ExperimentRow } from "../types";
import { plural } from "../util";

/** Most runs "select all" picks — and one archive job takes. */
export const SELECT_ALL_CAP = 500;

/** A selected run and what its row said of it. `job` is the job it belongs
 *  to: undefined = unknown, null = none (a single top-level run). */
export interface RunPick {
  verstr: string;
  job?: string | null;
  name?: string | null;
  idx?: number | null;
}

const KEY_PREFIX = "vmn-exp:selection:";
const keyOf = (ws: string, app: string) => `${KEY_PREFIX}${ws}/${app}`;
const listeners = new Set<() => void>();

/** The stored text, for change detection. */
export const rawPicks = (ws: string, app: string): string => sessionStorage.getItem(keyOf(ws, app)) ?? "[]";

export function parsePicks(raw: string): RunPick[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((p): p is RunPick => typeof p?.verstr === "string") : [];
  } catch {
    return [];
  }
}

export const readPicks = (ws: string, app: string): RunPick[] => parsePicks(rawPicks(ws, app));

/** Store *picks* (deduplicated, capped) and tell every subscriber. */
export function writePicks(ws: string, app: string, picks: readonly RunPick[], notify = true) {
  const seen = new Set<string>();
  const kept = picks.filter((p) => !seen.has(p.verstr) && seen.add(p.verstr)).slice(0, SELECT_ALL_CAP);
  if (kept.length) sessionStorage.setItem(keyOf(ws, app), JSON.stringify(kept));
  else sessionStorage.removeItem(keyOf(ws, app));
  if (notify) notifySelection();
}

/** Tell every subscriber the selection changed. */
export const notifySelection = () => listeners.forEach((l) => l());

export function subscribePicks(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Whether a board's row is a job (a run with children). */
export const isJobRow = (r: ExperimentRow) => r.kind === "outer" || !!r.job || !!r.children?.length;

/** A row as a pick: its job is its root, else its parent, else itself for
 *  a top-level job (which counts as one run, never its subtree). */
export function pickOf(r: ExperimentRow): RunPick {
  const job = r.root ?? r.parent ?? (isJobRow(r) ? r.verstr : null);
  const pick: RunPick = { verstr: r.verstr, job };
  if (r.name) pick.name = r.name;
  if (r.idx != null) pick.idx = r.idx;
  return pick;
}

/** `7 runs from 3 jobs`, `1 run`; *queries* add their counts and jobs. */
export function summarizePicks(picks: readonly RunPick[], queries: readonly { job: string; count: number }[] = []) {
  const jobs = new Set([...picks.map((p) => p.job), ...queries.map((g) => g.job)].filter(Boolean)).size;
  const runs = picks.length + queries.reduce((n, g) => n + g.count, 0);
  const text = jobs ? `${plural(runs, "run")} from ${plural(jobs, "job")}` : plural(runs, "run");
  return { runs, jobs, text };
}

export interface PickGroup {
  /** null: the runs of no (known) job. */
  job: string | null;
  label: string;
  picks: RunPick[];
}

/** The picks by job, in pick order, the runs outside a known job last. */
export function groupPicks(picks: readonly RunPick[]): PickGroup[] {
  const groups = new Map<string | null, RunPick[]>();
  const names = new Map(picks.map((p) => [p.verstr, p.name]));
  for (const p of picks) {
    const job = p.job ?? null;
    const group = groups.get(job);
    if (group) group.push(p);
    else groups.set(job, [p]);
  }
  const named = (job: string) => names.get(job) || job;
  const jobs = [...groups].filter(([job]) => job !== null)
    .map(([job, ps]) => ({ job, label: named(job!), picks: ps }));
  const loose = groups.get(null);
  return loose ? [...jobs, { job: null, label: "Runs outside a job", picks: loose }] : jobs;
}
