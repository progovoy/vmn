/** The failure card's context lines (plan 20 K4/B4): where the run
 *  stopped, the last run of its command that worked, and its last output. */
import { useLayoutEffect, useRef } from "react";
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

/** A `<pre>` ref kept scrolled to its end, where the last line is. */
export function useScrolledToEnd(text: string) {
  const ref = useRef<HTMLPreElement>(null);
  const scroll = () => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; };
  useLayoutEffect(scroll, [text]);
  return [ref, scroll] as const;
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
  // A closed <details> has no height to scroll, so opening it scrolls too.
  const [ref, scroll] = useScrolledToEnd(text);
  return (
    <details className="run-error-output" open={open} onToggle={scroll}>
      <summary>last output</summary>
      <pre ref={ref} className="yaml-block mono run-error-tail">{text}</pre>
      {fullOutputHref && <a className="run-error-full" href={fullOutputHref}>open full output</a>}
    </details>
  );
}
