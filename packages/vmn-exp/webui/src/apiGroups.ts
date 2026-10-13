/** The grouped leaderboard (plan 22 K1): `.../experiments?group=` answers
 *  groups of runs, each with its header run or label, status counts,
 *  per-metric aggregates and its first rows. */
import { setFilter } from "./api";
import type { PageOpts } from "./api";
import { appTag, get } from "./http";
import type { ExperimentRow } from "./types";

/** Links between runs (the run pointed at heads the group; `code_verstr`:
 *  the code state) and row fields. */
export type GroupLink = "parent" | "forked_from" | "rerun_of" | "code_verstr";
export type GroupField = GroupLink | "branch" | "status" | `tags.${string}` | `params.${string}`;

/** What orders groups by the sort metric; `best` follows the metric's goal
 *  (the mean for a goal-less metric). */
export const GROUP_AGGREGATES = ["mean", "best", "median", "min", "max"] as const;
export type GroupAggregate = (typeof GROUP_AGGREGATES)[number];

/** The key of the group of runs without a value (`(no parent run)` for `parent`); last. */
export const NONE_GROUP = "(none)";

export interface GroupCounts {
  total: number;
  running: number;
  waiting: number;
  done: number;
  failed: number;
  stuck: number;
}

/** A metric's finite values over a group; null when it has none (`best`:
 *  also without a goal). */
export interface MetricAggregate {
  mean: number | null;
  best: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

/** A link group's header run (`parent`/`forked_from`/`rerun_of`). */
export interface GroupTarget {
  verstr: string;
  idx: number | null;
  name: string | null;
  status: string | null;
  tree_status: string | null;
  metrics: Record<string, number | null>;
}

export interface RunGroup {
  key: string;
  /** The target's verstr, `<verstr> (not found)`, the code verstr, `branch = main`,
   *  `(none)` or `(no parent run)`. */
  label: string;
  /** Null for `code_verstr`, field groups, `(none)` and a target not in the index. */
  target: GroupTarget | null;
  counts: GroupCounts;
  aggregates: Record<string, MetricAggregate>;
  rows: ExperimentRow[];
  rows_total: number;
}

export interface GroupedPage {
  groups: RunGroup[];
  total_groups: number;
  total_rows: number;
  /** What `agg=` resolved to (the app's conf default without one; F3). */
  aggregate?: GroupAggregate;
  /** Running rows across all groups, after the filters (F4). */
  running?: number;
}

export interface GroupOpts extends Omit<PageOpts, "last"> {
  group: GroupField;
  /** Absent: the app's conf `experiment.ui.group_aggregate`, else mean. */
  agg?: GroupAggregate;
  /** Rows per group, 1..100 (server default 10). */
  rowsPerGroup?: number;
}

function groupParams(opts: GroupOpts): URLSearchParams {
  const p = new URLSearchParams({ group: opts.group, offset: String(opts.offset ?? 0) });
  setFilter(p, opts);
  if (opts.agg) p.set("agg", opts.agg);
  return p;
}

const listUrl = (ws: string, app: string, p: URLSearchParams) =>
  `/workspaces/${ws}/apps/${appTag(app)}/experiments?${p}`;

/** A page of groups: `offset` and `limit` page groups, `rowsPerGroup` caps each one's rows. */
export function fetchGroups(ws: string, app: string, opts: GroupOpts): Promise<GroupedPage> {
  const p = groupParams(opts);
  if (opts.rowsPerGroup) p.set("rows_per_group", String(opts.rowsPerGroup));
  return get<GroupedPage>(listUrl(ws, app, p));
}

/** One group's rows from *offset* (the `+N more` row); 404 for an unknown key. */
export function fetchGroupRows(
  ws: string, app: string, key: string, opts: Omit<GroupOpts, "rowsPerGroup">,
): Promise<RunGroup> {
  const p = groupParams(opts);
  p.set("group_key", key);
  return get<RunGroup>(listUrl(ws, app, p));
}
