import { Link } from "react-router-dom";
import type { ForkOrigin as Origin, RunRewind } from "../types";

/** The run a rerun reran and where a forked run branched off (links to the
 *  source runs), and the steps a rewound run went back to. Nothing for a
 *  plain run. */
export function ForkOrigin({ forkedFrom, rerunOf, rewinds, runUrl }: {
  forkedFrom?: Origin | null;
  rerunOf?: string | null;
  rewinds?: RunRewind[];
  runUrl: (verstr: string) => string;
}) {
  const steps = (rewinds ?? []).map((r) => `to step ${r.step}`);
  if (!forkedFrom && !rerunOf && steps.length === 0) return null;
  return (
    <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>
      {rerunOf && (
        <div data-testid="rerun-of">
          rerun of <Link className="mono" to={runUrl(rerunOf)}>{rerunOf}</Link>
        </div>
      )}
      {forkedFrom && (
        <div data-testid="fork-origin">
          forked from <Link className="mono" to={runUrl(forkedFrom.verstr)}>{forkedFrom.verstr}</Link>
          {forkedFrom.step != null && ` @ step ${forkedFrom.step}`}
        </div>
      )}
      {steps.length > 0 && <div data-testid="run-rewinds">rewound {steps.join(", then ")}</div>}
    </div>
  );
}
