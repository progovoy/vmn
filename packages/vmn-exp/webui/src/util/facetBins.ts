/** A numeric param's facet (plan 23 W3): its values as a mini histogram,
 *  each bar a range clause for the filter bar. */
import { NONE_GROUP } from "../apiGroups";

export interface FacetBin {
  lo: number;
  hi: number;
  count: number;
  /** The last bin includes its upper edge. */
  last: boolean;
}

/** *n* rounded to 4 significant digits, so edges read as typed numbers. */
const tidy = (n: number) => Number(n.toPrecision(4));

/** The finite numbers among *values* in *count* equal-width bins (one bin
 *  when they are all the same). */
export function numericBins(values: readonly unknown[], count = 12): FacetBin[] {
  const nums = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!nums.length) return [];
  let min = Infinity;
  let max = -Infinity;
  for (const v of nums) { if (v < min) min = v; if (v > max) max = v; }
  if (min === max) return [{ lo: min, hi: max, count: nums.length, last: true }];
  const width = (max - min) / count;
  const edges = Array.from({ length: count + 1 }, (_, i) => (i === count ? max : tidy(min + i * width)));
  const bins = edges.slice(0, -1).map((lo, i) => ({ lo, hi: edges[i + 1], count: 0, last: i === count - 1 }));
  for (const v of nums) {
    let i = Math.min(count - 1, Math.floor((v - min) / width));
    while (i > 0 && v < bins[i].lo) i--;
    while (i < count - 1 && v >= bins[i].hi) i++;
    bins[i].count++;
  }
  return bins;
}

/** The clauses selecting *bin*'s runs of *field*. */
export function binClauses(field: string, bin: FacetBin): string[] {
  if (bin.lo === bin.hi) return [`${field} = ${bin.lo}`];
  return [`${field} >= ${bin.lo}`, `${field} ${bin.last ? "<=" : "<"} ${bin.hi}`];
}

const NUMBER = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/;

/** A column value's group key, as the grouped list spells it: text as is,
 *  anything else as JSON, no value the no-value group. */
function keyOf(v: unknown): string {
  if (v === null || v === undefined || v === "") return NONE_GROUP;
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** A column's *top* most common values (by count, then first seen) and how
 *  many distinct values it holds: a facet's counts without a grouping. */
export function columnCounts(column: readonly unknown[], top: number) {
  const counts = new Map<string, number>();
  for (const v of column) {
    const k = keyOf(v);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const values = [...counts].map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count).slice(0, top);
  return { values, distinct: counts.size };
}

/** Group keys as numbers when every one spells a number, else null. */
export function numericKeys(keys: readonly string[]): number[] | null {
  if (!keys.length || !keys.every((k) => NUMBER.test(k))) return null;
  return keys.map(Number);
}
