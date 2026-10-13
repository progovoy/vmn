/** One metric delta of an experiments-diff: its numeric change, signed text
 *  and whether it moved toward the metric's goal (Changes card, Compare code tab). */
import type { DiffDelta } from "../types";
import { fmtVal } from "../util";

export type DeltaTone = "better" | "worse" | "flat";

export function numericChange(d: DiffDelta): number | null {
  return typeof d.from === "number" && typeof d.to === "number" ? d.to - d.from : null;
}

export function deltaTone(d: DiffDelta, diff: number | null): DeltaTone {
  if (diff === null || diff === 0 || d.goal == null || d.param) return "flat";
  return (d.goal === "min" ? diff < 0 : diff > 0) ? "better" : "worse";
}

export function fmtDelta(diff: number | null): string {
  return diff === null ? "–" : (diff > 0 ? "+" : "") + fmtVal(diff);
}
