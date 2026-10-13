import type { ReactNode } from "react";
import { ParamsCard } from "./RunSections";
import "./runCards.css";

/** Params up to this many rows are about as tall as the Metadata card. */
export const SHORT_PARAMS = 8;

/** Metadata | Params, then Metrics. Cards keep their own height: a short
 *  Params card leaves Metrics the full width below; a long one gets its own
 *  column, with Metrics stacked under Metadata beside it. */
export default function RunCards({ metadata, params, metrics }: {
  metadata: ReactNode;
  params: Record<string, unknown> | null | undefined;
  metrics: ReactNode;
}) {
  const count = Object.keys(params ?? {}).length;
  if (count === 0) {
    return <div className="run-cards">{metadata}{metrics}</div>;
  }
  if (count > SHORT_PARAMS) {
    return (
      <div className="run-cards">
        <div className="run-cards-col">{metadata}{metrics}</div>
        <ParamsCard params={params} />
      </div>
    );
  }
  return (
    <div className="run-cards">
      {metadata}
      <ParamsCard params={params} />
      <div className="run-cards-wide">{metrics}</div>
    </div>
  );
}
