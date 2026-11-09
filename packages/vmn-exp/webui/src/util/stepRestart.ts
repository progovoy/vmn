import type { StepRestart } from "../types";
import { plural } from "../util";

/** Where a metric's steps went back: its value is still the last write. The
 *  run page knows the write; board rows and `/series` answers do not. */
export const restartText = (r: StepRestart) =>
  `steps went back from ${r.from} to ${r.to}${r.write != null ? ` at write ${r.write}` : ""}`;

/** A cell's mark title: where the steps went back, and what the value is. */
export const restartTitle = (r: StepRestart) => `${restartText(r)} · the value is the last write`;

/** An overlaid chart's note of the runs (`[label, restart]`) whose steps
 *  went back: one run named with where, several counted (each in the
 *  title); null without any. */
export function overlayRestartNote(went: [string, StepRestart][]): { text: string; title: string } | null {
  if (!went.length) return null;
  const title = went.map(([label, r]) => `${label}: ${restartText(r)}`).join("\n");
  if (went.length > 1) return { text: `steps went back in ${plural(went.length, "run")}`, title };
  const [label, r] = went[0];
  return { text: `steps went back in ${label}: from ${r.from} to ${r.to}`, title };
}
