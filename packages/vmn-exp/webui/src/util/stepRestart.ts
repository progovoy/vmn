import type { StepRestart } from "../types";

/** Where a metric's steps went back: its value is still the last write. */
export const restartText = (r: StepRestart) => `steps went back from ${r.from} to ${r.to} at write ${r.write}`;
