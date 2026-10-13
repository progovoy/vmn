/** The failure card's context lines (plan 20 K4/B4): where the run
 *  stopped, the last run of its command that worked, and its last output. */
import { Link } from "react-router-dom";
import type { ExperimentDetail } from "../types";
import { runText } from "../shell/crumbs";
import { CHANGES_ID, changesSearch } from "./runChangesBaseline";
import "./RunErrorCard.css";

export type FailureContext = Pick<ExperimentDetail, "output_tail" | "last_step" | "last_good">;

/** Lines of output the card shows, the server's cap too. */
export const TAIL_LINES = 40;

export function tailText(context: FailureContext | undefined, errorTail: string | null | undefined) {
  const lines = context?.output_tail?.lines;
  if (lines?.length) return lines.slice(-TAIL_LINES).join("\n");
  return errorTail || null;
}

export function StopStep({ lastStep }: { lastStep: FailureContext["last_step"] }) {
  if (!lastStep) return null;
  const of = lastStep.of != null ? ` of ${lastStep.of}` : "";
  return <div className="run-error-step">stopped at step {lastStep.step}{of}</div>;
}

/** "Since it last worked: @41 name → Changes", diffing this run against it. */
export function SinceLastGood({ lastGood, runPath }: {
  lastGood: FailureContext["last_good"]; runPath: string;
}) {
  if (!lastGood) return null;
  const to = `${runPath}?${changesSearch(lastGood.verstr)}#${CHANGES_ID}`;
  return (
    <div className="run-error-since">
      Since it last worked: <span className="mono" title={lastGood.verstr}>{runText(lastGood)}</span>
      {" → "}<Link to={to}>Changes</Link>
    </div>
  );
}

export function OutputTail({ text, open, fullOutputHref }: {
  text: string; open: boolean; fullOutputHref: string | null;
}) {
  return (
    <details className="run-error-output" open={open}>
      <summary>last output</summary>
      <pre className="yaml-block mono run-error-tail">{text}</pre>
      {fullOutputHref && <a className="run-error-full" href={fullOutputHref}>open full output</a>}
    </details>
  );
}
