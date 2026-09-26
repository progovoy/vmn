import type { CSSProperties } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { metricGoal, rowParams } from "../util";
import { finiteNumbers, maxOf, minOf } from "../util/stats";

/** Fixed column widths (px). The virtualized rows are absolutely positioned,
 *  which takes each <tr> out of the table's layout — so header and rows only
 *  line up when every cell gets the same explicit width under
 *  `table-layout: fixed`. */
const W = {
  check: 34, idx: 56, status: 110, experiment: 300,
  metric: 110, param: 120, tags: 180, note: 200, when: 90,
};
const MIN_TABLE_WIDTH = 760;

/** Index of the "experiment" column — the run identifier that stays pinned
 *  to the left edge while scrolling horizontally (see columnStyles). */
export const EXPERIMENT_COL_INDEX = 3;

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

/** Columns in order: check, #, status, experiment, cells…, [tags], note, when.
 *  Each cell contributes its own width (metric = 110, param = 120). */
export function columnLayout(cells: readonly ColumnCell[], tags = false): ColumnLayout {
  const cellsWidth = cells.reduce((s, c) => s + (c.kind === "metric" ? W.metric : W.param), 0);
  const fixed = W.check + W.idx + W.status + W.note + W.when + cellsWidth + (tags ? W.tags : 0);
  const experiment = Math.max(W.experiment, MIN_TABLE_WIDTH - fixed);
  const widths = [
    W.check, W.idx, W.status, experiment,
    ...cells.map((c) => (c.kind === "metric" ? W.metric : W.param)),
    ...(tags ? [W.tags] : []),
    W.note, W.when,
  ];
  return { widths, total: fixed + experiment };
}

/** One shared style object per column: every cell of a column gets the same
 *  object, so a re-render allocates nothing per cell and React skips the
 *  style diff entirely.
 *
 *  The experiment column and the first `pinnedCount` metric/param cells pin
 *  themselves to the left edge with cumulative `left` offsets so they stay
 *  visible while scrolling sideways. */
export function columnStyles(layout: ColumnLayout, pinnedCount = 0): CSSProperties[] {
  const FIRST_CELL = EXPERIMENT_COL_INDEX + 1;
  const stickyLeft = layout.widths
    .slice(0, EXPERIMENT_COL_INDEX)
    .reduce((sum, w) => sum + w, 0);

  // Pre-compute the left offset for each pinned metric/param cell.
  const pinnedLefts: number[] = [];
  let acc = stickyLeft + layout.widths[EXPERIMENT_COL_INDEX];
  for (let i = 0; i < pinnedCount; i++) {
    pinnedLefts.push(acc);
    acc += layout.widths[FIRST_CELL + i] ?? 0;
  }

  return layout.widths.map((w, i) => {
    if (i === EXPERIMENT_COL_INDEX) {
      return { width: `${w}px`, position: "sticky", left: stickyLeft, zIndex: 1, background: STICKY_BG };
    }
    const cellIdx = i - FIRST_CELL;
    if (cellIdx >= 0 && cellIdx < pinnedCount) {
      return { width: `${w}px`, position: "sticky", left: pinnedLefts[cellIdx], zIndex: 1, background: STICKY_BG };
    }
    return { width: `${w}px` };
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
