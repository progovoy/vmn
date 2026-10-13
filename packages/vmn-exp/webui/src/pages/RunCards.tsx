import type { ReactNode } from "react";
import { ParamsCard } from "./RunSections";
import "./runCards.css";

/** Params | Metrics (plan 20 D5 7). Cards keep their own height; without
 *  params, Metrics takes the full width. */
export default function RunCards({ params, metrics }: {
  params: Record<string, unknown> | null | undefined;
  metrics: ReactNode;
}) {
  if (Object.keys(params ?? {}).length === 0) {
    return <div className="run-cards"><div className="run-cards-wide">{metrics}</div></div>;
  }
  return (
    <div className="run-cards">
      <ParamsCard params={params} />
      {metrics}
    </div>
  );
}
