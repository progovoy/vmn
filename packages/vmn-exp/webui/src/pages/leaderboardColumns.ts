import type { CSSProperties } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { metricGoal, rowParams } from "../util";
import { finiteNumbers, maxOf, minOf } from "../util/stats";

/** Default column widths (px) under `table-layout: fixed`, so a long value
 *  is clipped with an ellipsis instead of stretching its column. */
const W = {
  check: 34, idx: 56, status: 110, experiment: 300, fleet: 76, date: 150,
  metric: 110, param: 120, tags: 180, note: 200, when: 90,
};
/** Narrowest a column can be dragged to. */
export const MIN_COL_WIDTH = 40;

/** The outer-run management columns, right after the experiment column:
 *  the inner-run tally and the run's own start/end. */
export const FLEET_COLS = ["total", "waiting", "running", "done", "failed", "started", "ended"] as const;
export type FleetCol = (typeof FLEET_COLS)[number];

/** The server sort key behind each sortable date column. */
export const DATE_SORT_OF: Readonly<Record<string, "started_at" | "finished_at">> = {
  "c:started": "started_at", "c:ended": "finished_at",
};

/** Inner runs of *r* per management column (null: not an outer run). */
export function fleetCounts(r: ExperimentRow): Record<Exclude<FleetCol, "started" | "ended">, number> | null {
  if (!r.children?.length) return null;
  const c = r.child_counts ?? {};
  const n = (k: string) => c[k] ?? 0;
  return {
    total: r.fleet?.expected ?? r.children.length,
    waiting: n("created"), running: n("running"), done: n("succeeded"), failed: n("failed") + n("stuck"),
  };
}
const MIN_TABLE_WIDTH = 760;

/** The columns that always lead the table, in this order, and never move. */
export const PINNED_COLS = ["check", "idx", "status", "experiment"] as const;
const PINNED = new Set<string>(PINNED_COLS);
export const isPinned = (id: string) => PINNED.has(id);

/** Index of the "experiment" column — the run identifier that stays pinned
 *  to the left edge while scrolling horizontally (see columnStyles). */
export const EXPERIMENT_COL_INDEX = PINNED_COLS.indexOf("experiment");

/** Solid theme background for every sticky header/pinned-column cell, so
 *  scrolled-under content never shows through. Shared with LeaderboardTable's
 *  header styling, and the same variable the compare-runs table's
 *  `.compare-key` sticky column already uses. */
export const STICKY_BG = "var(--surface-1)";

export interface ColumnLayout {
  widths: number[];
  total: number;
}

/** A single visible metric-or-param column, in rendered order. */
export interface ColumnCell {
  kind: "metric" | "param";
  key: string;
}

/** The column id of *cell* (`m:<metric>` / `p:<param>`). */
export const cellId = (cell: ColumnCell) => `${cell.kind === "metric" ? "m" : "p"}:${cell.key}`;

/** Column ids in order: check, #, status, experiment, fleet…, *cells*
 *  (metric/param ids), [tags], [comments], note, when. Ids use the `hide=` prefixes
 *  (`c:`, `m:`, `p:`), so `c:tags` is the tags column. */
export function columnIds(
  fleet: readonly string[], cells: readonly string[], tags: boolean, comments = false,
): string[] {
  return [
    ...PINNED_COLS, ...fleet.map((c) => `c:${c}`), ...cells, ...(tags ? ["c:tags"] : []),
    ...(comments ? ["c:comments"] : []), "note", "when",
  ];
}

/** Column ids in their default order: metrics before params. */
export function defaultColumnIds(
  fleet: readonly string[], metrics: readonly string[], params: readonly string[], tags: boolean,
): string[] {
  return columnIds(fleet, [...metrics.map((c) => `m:${c}`), ...params.map((c) => `p:${c}`)], tags);
}

/** Default widths for check, #, status, experiment, *cells*…, [tags], note, when. */
export function columnLayout(cells: readonly ColumnCell[], tags = false): ColumnLayout {
  return idLayout(columnIds([], cells.map(cellId), tags));
}

export function defaultWidth(id: string): number {
  if (id in DATE_SORT_OF) return W.date;
  if (id === "c:tags") return W.tags;
  const prefix = id.slice(0, 2);
  if (prefix === "c:") return W.fleet;
  if (prefix === "m:") return W.metric;
  if (prefix === "p:") return W.param;
  return W[id as keyof typeof W] ?? W.metric;
}

/** *ids* (default order) rearranged to follow *saved*: saved columns keep
 *  their saved order, and a column the saved order doesn't know lands right
 *  after the column it follows by default. Pinned columns never move. */
export function orderColumns(ids: readonly string[], saved: readonly string[]): string[] {
  const pinned = ids.filter(isPinned);
  const rest = ids.filter((id) => !isPinned(id));
  if (!saved.length) return [...pinned, ...rest];
  const known = new Set(rest);
  const out = saved.filter((id) => known.has(id));
  const placed = new Set(out);
  rest.forEach((id, i) => {
    if (placed.has(id)) return;
    const prev = i > 0 ? out.indexOf(rest[i - 1]) : -1;
    out.splice(prev + 1, 0, id);
  });
  return [...pinned, ...out];
}

/** *order* with *from* moved in front of *to* (pinned columns stay put). */
export function moveColumn(order: readonly string[], from: string, to: string): readonly string[] {
  if (from === to || isPinned(from) || isPinned(to)) return order;
  const out = order.filter((id) => id !== from);
  out.splice(out.indexOf(to), 0, from);
  return out;
}

/** Widths for *ids*: the user's where set, else the default — with an
 *  untouched experiment column growing so the table fills *fill* px (at
 *  least its minimum). */
export function idLayout(
  ids: readonly string[], custom: Readonly<Record<string, number>> = {}, fill = 0,
): ColumnLayout {
  const widths = ids.map((id) => custom[id] ?? defaultWidth(id));
  const exp = ids.indexOf("experiment");
  if (exp >= 0 && custom.experiment === undefined) {
    const others = widths.reduce((a, b) => a + b, 0) - widths[exp];
    widths[exp] = Math.max(widths[exp], Math.max(MIN_TABLE_WIDTH, fill) - others);
  }
  return { widths, total: widths.reduce((a, b) => a + b, 0) };
}

/** One shared style object per column: every cell of a column gets the same
 *  object, so a re-render allocates nothing per cell and React skips the
 *  style diff entirely.
 *
 *  The columns up to and including the experiment column pin themselves to
 *  the left edge as one block, so the run identifier and its status stay
 *  visible while scrolling sideways; the next `pinnedCount` columns (the
 *  URL-pinned cells) stick right after them with cumulative offsets. */
export function columnStyles(layout: ColumnLayout, pinnedCount = 0): CSSProperties[] {
  let left = 0;
  return layout.widths.map((w, i) => {
    if (i > EXPERIMENT_COL_INDEX + pinnedCount) return { width: `${w}px` };
    const style: CSSProperties = {
      width: `${w}px`, position: "sticky", left, zIndex: 1, background: STICKY_BG,
    };
    left += w;
    return style;
  });
}

/** A stable identity for the set of param names across rows, so a poll that
 *  returns the same names doesn't look like a new column set. */
export function paramKey(
  rows: readonly ExperimentRow[] | null | undefined,
  facetKeys?: readonly string[],
): string {
  const keys = new Set<string>(facetKeys ?? []);
  rows?.forEach((r) => Object.keys(rowParams(r)).forEach((k) => keys.add(k)));
  return [...keys].sort().join("\u0000");
}

/** Whether any row carries a tag — the tags column only exists then. */
export function anyTags(rows: readonly ExperimentRow[] | undefined): boolean {
  return Boolean(rows?.some((r) => r.tags && Object.keys(r.tags).length > 0));
}

/** Whether any row carries comment counts — the comments column only exists then. */
export function anyComments(rows: readonly ExperimentRow[] | undefined): boolean {
  return Boolean(rows?.some((r) => r.comments));
}

/** Metric columns: the schema's order first, then any other metric the rows
 *  (or, when given, the app-wide facets) carry, alphabetically. A key that
 *  is also a param (numeric params fold into `metrics` too — see
 *  CLAUDE.md) is left there instead: it's a hyperparameter, not something
 *  being optimized, so it stays a param column rather than showing up a
 *  second time as a metric. */
export function metricColumns(
  rows: readonly ExperimentRow[],
  schema: MetricsSchema | null,
  facetKeys?: readonly string[],
): string[] {
  const inData = new Set<string>(facetKeys ?? []);
  rows.forEach((r) => Object.keys(r.metrics).forEach((k) => inData.add(k)));
  const inParams = new Set<string>();
  rows.forEach((r) => Object.keys(rowParams(r)).forEach((k) => inParams.add(k)));
  const fromSchema = Object.keys(schema ?? {}).filter((k) => inData.has(k) && !inParams.has(k));
  const extras = [...inData].filter((k) => !(schema ?? {})[k] && !inParams.has(k)).sort();
  return [...fromSchema, ...extras];
}

export interface ColMeta {
  goal: "min" | "max";
  best: number | null;
  isBar: boolean;
  min: number;
  max: number;
}

/** Per metric column: its goal, best value and the span its bar scales over. */
export function computeColMeta(
  rows: readonly ExperimentRow[],
  metricCols: readonly string[],
  schema: MetricsSchema | null,
  primary: string | null,
): Record<string, ColMeta> {
  const meta: Record<string, ColMeta> = {};
  metricCols.forEach((m) => {
    const goal = metricGoal(schema, m);
    const vals = finiteNumbers(rows.map((r) => r.metrics[m]));
    const min = minOf(vals);
    const max = maxOf(vals);
    meta[m] = {
      goal,
      best: vals.length ? (goal === "min" ? min : max) : null,
      isBar: m === primary && vals.length > 0,
      min, max,
    };
  });
  return meta;
}
