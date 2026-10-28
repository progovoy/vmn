/** The pivot heatmap's cells (plan 28 N2): what each says, its fill on one
 *  sequential hue (the accent, more is darker on light and brighter on
 *  dark, the low end receding into the panel), its ink (a text token,
 *  picked to read on the fill) and the board query it links to. Pure. */
import type { Pivot, PivotCell, PivotKind } from "../apiPivot";
import type { ExperimentFacets } from "../types";
import { fmtCount, fmtVal, plural } from "../util";
import { maxOf, minOf } from "./stats";

/** The fill's share of the accent at the low and high ends. */
const LOW_MIX = 12;
const HIGH_MIX = 85;
/** Past this share of the accent, the fill takes the background's ink. */
const DARK_MIX = 50;

const pct = (share: number) => `${Math.round(share * 100)}%`;

/** A value as a cell and the legend say it. */
export const scaleText = (value: number, kind: PivotKind) => (kind === "share" ? pct(value) : fmtVal(value));

export function cellText(cell: PivotCell, kind: PivotKind): string {
  if (kind === "count") return fmtCount(cell.n);
  return cell.value === null ? "–" : scaleText(cell.value, kind);
}

/** `[low, high]` the fills span: a share's 0..1, else its cells' values. */
export function pivotRange(pivot: Pivot): [number | null, number | null] {
  if (pivot.cell === "share") return [0, 1];
  const values = pivot.cells.flat().map((c) => c?.value);
  const lo = minOf(values), hi = maxOf(values);
  return Number.isNaN(lo) ? [null, null] : [lo, hi];
}

export function cellFill(value: number | null, [lo, hi]: [number | null, number | null]) {
  if (value === null || lo === null || hi === null) return { background: "var(--panel-2)", color: "var(--text-3)" };
  const t = hi > lo ? (value - lo) / (hi - lo) : 1;
  const mix = Math.round(LOW_MIX + t * (HIGH_MIX - LOW_MIX));
  return {
    background: `color-mix(in srgb, var(--accent) ${mix}%, var(--panel))`,
    color: mix > DARK_MIX ? "var(--bg)" : "var(--text)",
  };
}

function what(pivot: Pivot, cell: PivotCell): string {
  if (pivot.cell === "count") return plural(cell.n, "run");
  if (pivot.cell === "share") {
    return `${cellText(cell, "share")} match ${pivot.match} (${fmtCount(cell.hits ?? 0)} of ${plural(cell.n, "run")})`;
  }
  const value = cell.value === null ? "no value" : fmtVal(cell.value);
  return `${pivot.agg} ${pivot.metric} ${value} (${plural(cell.n, "run")})`;
}

/** What a screen reader and the tooltip say of cell (*i*, *j*). */
export function cellLabel(pivot: Pivot, rowsField: string, colsField: string, i: number, j: number, cell: PivotCell): string {
  return `${rowsField} ${pivot.rows[i].label}, ${colsField} ${pivot.cols[j].label}: ${what(pivot, cell)}`;
}

/** The board query of a cell's runs (a share cell's: its matching ones), or null. */
export function cellQuery(pivot: Pivot, cell: PivotCell): string | null {
  if (!cell.clause) return null;
  return pivot.cell === "share" && pivot.match ? `${cell.clause} and (${pivot.match})` : cell.clause;
}

/** *query* within *base* (a panel's or a page's own query), if any. */
export const withQuery = (base: string | null | undefined, query: string) =>
  (base && base.trim() ? `(${base}) and ${query}` : query);

/** The fields a pivot axis offers: tags, params, status, branch, then the
 *  ancestors' tags and params (plan 28 N1). */
export function fieldOptions(facets: Pick<ExperimentFacets, "tag_keys" | "param_keys">): string[] {
  const own = [...(facets.tag_keys ?? []).map((k) => `tags.${k}`), ...(facets.param_keys ?? []).map((k) => `params.${k}`)];
  return [...own, "status", "branch", ...own.map((f) => `up.${f}`)];
}

/** The axes a pivot opens on: the first two fields. */
export const defaultAxes = (fields: string[]): [string, string] => [fields[0], fields[1] ?? fields[0]];
