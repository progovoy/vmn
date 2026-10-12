import { Link } from "react-router-dom";
import { curvelessRuns, noCurvesNote } from "../pages/overlayCoverage";
import type { OverlayRunData } from "../pages/overlaySeries";

const overlayHref = (ws: string, app: string, runs: string[]) =>
  `/ws/${ws}/app/${app}/overlay?runs=${runs.map(encodeURIComponent).join(",")}`;

const shortRef = (r: OverlayRunData) => (r.idx != null ? `@${r.idx}` : r.key);
const trials = (n: number) => `${n} trial${n === 1 ? "" : "s"}`;

/** Links overlaying each curveless sweep (outer) run's trials instead,
 *  naming the sweep once there are several. */
export function TrialLinks({ ws, app, runs }: { ws: string; app: string; runs: OverlayRunData[] }) {
  const sweeps = runs.filter((r) => r.kind === "outer" && (r.children?.length ?? 0) > 0);
  if (sweeps.length === 0) return null;
  return (
    <>
      {sweeps.map((r) => (
        <Link key={r.key} to={overlayHref(ws, app, r.children!)} style={{ marginLeft: 8 }}>
          overlay {sweeps.length > 1 ? `${shortRef(r)}'s` : "its"} {trials(r.children!.length)}
        </Link>
      ))}
    </>
  );
}

/** One quiet line naming the selected runs that drew no curve at all. */
export default function OverlayNoCurves({ ws, app, runs }: {
  ws: string;
  app: string;
  runs: OverlayRunData[];
}) {
  const note = noCurvesNote(runs);
  if (!note) return null;
  return (
    <p style={{ color: "var(--text-3)", margin: "0 0 12px", fontSize: 12 }}>
      <span>{note}</span>
      <TrialLinks ws={ws} app={app} runs={curvelessRuns(runs)} />
    </p>
  );
}
