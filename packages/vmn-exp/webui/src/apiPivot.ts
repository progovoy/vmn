/** The pivot heatmap's endpoint (plan 28 N2): an app's runs, or an outer
 *  run's subtree (`scope`), crossed by two group fields. */
import type { GroupAggregate } from "./apiGroups";
import { appTag, get } from "./http";

export type PivotKind = "count" | "share" | "agg";

/** One value of an axis: its runs and the clause selecting them. */
export interface PivotHeader {
  key: string;
  label: string;
  n: number;
  clause: string | null;
}

/** A cell's runs, its value (a count, a 0..1 share or an aggregate, null
 *  when no run carries the metric) and the clause selecting its runs;
 *  `hits`: the runs matching a share's query. */
export interface PivotCell {
  n: number;
  value: number | null;
  clause: string | null;
  hits?: number;
}

/** At most 200 rows x 50 columns, the most common values; `*_total` the
 *  distinct values in all. An empty cell is null. */
export interface Pivot {
  rows: PivotHeader[];
  cols: PivotHeader[];
  cells: (PivotCell | null)[][];
  total: number;
  rows_total: number;
  cols_total: number;
  cell: PivotKind;
  match: string | null;
  metric: string | null;
  agg: GroupAggregate | null;
}

export interface PivotParams {
  rows: string;
  cols: string;
  cell?: PivotKind;
  match?: string;
  metric?: string;
  agg?: GroupAggregate;
  q?: string;
  status?: string;
  scope?: string;
  archived?: boolean;
}

export function pivot(ws: string, app: string, params: PivotParams): Promise<Pivot> {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "" && v !== false) p.set(k, String(v));
  return get<Pivot>(`/workspaces/${ws}/apps/${appTag(app)}/experiments-pivot?${p}`);
}
