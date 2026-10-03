/** A report panel: validates a `vmn-panel` spec and renders the component
 *  its type maps to, mounted only once scrolled near the viewport. */
import type { ReactNode } from "react";
import LazyMount from "../components/LazyMount";
import OverlayChart from "../components/OverlayChart";
import { AUTO_X } from "../util/xMetric";
import { validate, type PanelSpec } from "./panelSpec";
import { useQueryVerstrs } from "./panelData";
import { ROW_TYPES, RowPanel, type RowSpec } from "./RowPanels";
import { RUN_TYPES, RunPanel, type RunSpec } from "./RunPanels";

const DEFAULT_HEIGHT = 300;

type CurvesSpec = Extract<PanelSpec, { type: "curves" }>;

export function PanelError({ message }: { message: string }) {
  return (
    <div role="alert" className="md-panel md-panel-error">
      Invalid panel: {message}
    </div>
  );
}

function Curves({ ws, spec, verstrs }: { ws: string; spec: CurvesSpec; verstrs: string[] }) {
  const x = spec.x;
  return (
    <OverlayChart ws={ws} app={spec.app} verstrs={verstrs} keys={spec.keys} maxPoints={spec.max_points}
      smoothing={spec.smoothing} logY={spec.log_y}
      xMode={x?.mode === "metric" ? "step" : x?.mode} x={x?.mode === "metric" && x.metric ? x.metric : AUTO_X} />
  );
}

function QueryCurves({ ws, spec }: { ws: string; spec: CurvesSpec & { runs: { query: string } } }) {
  return <Curves ws={ws} spec={spec} verstrs={useQueryVerstrs(ws, spec.app, spec.runs)} />;
}

function body(ws: string, spec: PanelSpec): ReactNode {
  if (spec.type === "curves") {
    const runs = spec.runs;
    return "verstrs" in runs
      ? <Curves ws={ws} spec={spec} verstrs={runs.verstrs} />
      : <QueryCurves ws={ws} spec={{ ...spec, runs }} />;
  }
  if (ROW_TYPES.has(spec.type)) return <RowPanel ws={ws} spec={spec as RowSpec} />;
  if (RUN_TYPES.has(spec.type)) return <RunPanel ws={ws} spec={spec as RunSpec} />;
  return null;
}

export default function Panel({ ws, spec }: { ws: string; spec: unknown }) {
  const result = validate(spec);
  if (!result.ok) return <PanelError message={result.error} />;
  const s = result.spec;
  return (
    <div className="md-panel" data-panel-id={s.id}>
      {s.title && <div className="eyebrow">{s.title}</div>}
      <LazyMount height={s.height ?? DEFAULT_HEIGHT}>{body(ws, s)}</LazyMount>
    </div>
  );
}
