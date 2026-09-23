import type { ExperimentRow } from "../types";
import { rowParams } from "../util";

/** Fixed column widths (px). The virtualized rows are absolutely positioned,
 *  which takes each <tr> out of the table's layout — so header and rows only
 *  line up when every cell gets the same explicit width under
 *  `table-layout: fixed`. */
const W = {
  check: 34, idx: 56, status: 110, experiment: 300,
  metric: 110, param: 120, note: 200, when: 90,
};
const MIN_TABLE_WIDTH = 760;

export interface ColumnLayout {
  widths: number[];
  total: number;
}

export function columnLayout(nMetrics: number, nParams: number): ColumnLayout {
  const fixed =
    W.check + W.idx + W.status + W.note + W.when +
    nMetrics * W.metric + nParams * W.param;
  const experiment = Math.max(W.experiment, MIN_TABLE_WIDTH - fixed);
  const widths = [
    W.check, W.idx, W.status, experiment,
    ...Array<number>(nMetrics).fill(W.metric),
    ...Array<number>(nParams).fill(W.param),
    W.note, W.when,
  ];
  return { widths, total: fixed + experiment };
}

/** A stable identity for the set of param names across rows, so a poll that
 *  returns the same names doesn't look like a new column set. */
export function paramKey(rows: readonly ExperimentRow[] | null): string {
  const keys = new Set<string>();
  rows?.forEach((r) => Object.keys(rowParams(r)).forEach((k) => keys.add(k)));
  return [...keys].sort().join("\u0000");
}
