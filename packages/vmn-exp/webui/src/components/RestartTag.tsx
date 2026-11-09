import type { StepRestart } from "../types";
import { restartTitle } from "../util/stepRestart";

/** A metric value's mark that its steps went back (a restarted step counter). */
export default function RestartTag({ restart }: { restart: StepRestart | undefined }) {
  if (!restart) return null;
  const title = restartTitle(restart);
  return <span className="restart-tag" title={title} aria-label={title}>↺</span>;
}
