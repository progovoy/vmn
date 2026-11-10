/** The grouped leaderboard (plan 22 K1): `.../experiments?group=` answers
 *  groups of runs, each with its header run or label, status counts,
 *  per-metric aggregates and its first rows. */
import { setFilter } from "./api";
import type { PageOpts } from "./api";
import { appTag, get } from "./http";
import type { ExperimentRow, JobCounts, JobRolled, MainMetric, PolicyMix } from "./types";
import type { Indexing } from "./util/indexing";

/** Links between runs (the run pointed at heads the group; `code_verstr`:
 *  the code state) and row fields. */
export type GroupLink = "parent" | "forked_from" | "rerun_of" | "code_verstr";
export type GroupField = GroupLink | "branch" | "status" | "failure_sig" | `tags.${string}` | `params.${string}`;

/** What orders groups by the sort metric; `best` and the tails (`best10`,
 *  `worst10`: the p90/p10 the goal points at) follow the metric's goal (no
 *  value for a goal-less metric). */
export const GROUP_AGGREGATES = ["mean", "best", "median", "min", "max", "best10", "worst10"] as const;
export type GroupAggregate = (typeof GROUP_AGGREGATES)[number];

/** The key of the group of runs without a value, last, labelled `(none)`
 *  (for a link grouping, the loose rows: {@link RunGroup.loose}). No value's
 *  key equals it: a value whose text starts with it is keyed with it doubled
 *  (plan 22 F6). */
export const NONE_GROUP = "\u2205";

/** The value a group key other than {@link NONE_GROUP} stands for. */
export const groupKeyText = (key: string): string =>
  key.startsWith(NONE_GROUP) ? key.slice(NONE_GROUP.length) : key;

export interface GroupCounts {
  total: number;
  running: number;
  waiting: number;
  done: number;
  failed: number;
  stuck: number;
}

/** A metric's finite values over a group; null when it has none (`best`:
 *  also without a goal). `goal` is the metric's (null: none, no best). */
export interface MetricAggregate extends PolicyMix {
  mean: number | null;
  best: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
  best10?: number | null;
  worst10?: number | null;
  n: number;
  goal: "min" | "max" | null;
}

/** A grouped Outer runs header's aggregate (plan 34 §1): the rows'
 *  aggregate over the units of all the group's outer runs (its attempts)
 *  pooled, a unit in several from the latest attempt; `from_earlier` the
 *  units taken from earlier ones (0 for `runs`). The other aggregates of
 *  the pooled values ride along (none for `runs`). */
export type PooledAggregate = JobRolled & PolicyMix & Partial<Omit<MetricAggregate, "n" | "goal">> & {
  from_earlier: number;
};

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
  /** The target's verstr, `<verstr> (not found)`, the code verstr, `branch = main`
   *  or `(none)`. */
  label: string;
  /** Null for `code_verstr`, field groups, `(none)` and a target not in the index. */
  target: GroupTarget | null;
  /** True for a link grouping's (`parent`/`forked_from`/`rerun_of`) runs with
   *  no link that head no group (plan 22 F12): not a group, so the board
   *  shows them as plain rows after the groups, with no header. */
  loose: boolean;
  counts: GroupCounts;
  aggregates: Record<string, MetricAggregate>;
  /** A grouped Outer runs page's (`top=`): `{rolled.metric: pooled}`, the
   *  units of all its outer runs pooled (plan 34 §1); empty when none has a value. */
  job_aggregates?: Record<string, PooledAggregate>;
  /** Its outer runs' run `counts`, summed (`top=`). */
  run_counts?: JobCounts;
  rows: ExperimentRow[];
  rows_total: number;
  /** The group's size with the same `archived` setting but without
   *  `q`/`status` (= `rows_total` when no filter is set; plan 22 F1). */
  rows_unfiltered: number;
  /** The group as a filter clause (`params.lr = 0.01`; plan 23 S7); null
   *  for a link grouping and for a key no literal can hold. */
  clause: string | null;
}

export interface GroupedPage {
  groups: RunGroup[];
  total_groups: number;
  total_rows: number;
  /** What `agg=` resolved to: the URL's, else the app's conf default (its
   *  branch conf respected), else mean (plan 22 F3). */
  aggregate: GroupAggregate;
  /** Running rows across every group after the filters (plan 22 F4). */
  running: number;
  /** The metric the groups sort by and its goal (null: none, `best` has no value). */
  metric: string | null;
  goal: "min" | "max" | null;
  /** A Jobs view page's main metric (`top=`). */
  main?: MainMetric;
  /** Why the query matched nothing (plan 31 §4.2). */
  hints?: string[];
  /** The index the answer is from still loading (plan 33 §2.2). */
  indexing?: Indexing;
}

export interface GroupOpts extends Omit<PageOpts, "last"> {
  group: GroupField;
  /** Absent: the app's conf `experiment.ui.group_aggregate`, else mean. */
  agg?: GroupAggregate;
  /** Rows per group (server default 10), clamped to 1..100; the server
   *  pages at most 50 groups and 5000 rows (plan 22 F5). */
  rowsPerGroup?: number;
  /** One row per group (plan 34 §1): the headers alone. */
  collapseAll?: boolean;
}

function groupParams(opts: GroupOpts): URLSearchParams {
  const p = new URLSearchParams({ group: opts.group, offset: String(opts.offset ?? 0) });
  setFilter(p, opts);
  if (opts.agg) p.set("agg", opts.agg);
  if (opts.collapseAll) p.set("collapse_all", "1");
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
