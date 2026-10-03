/** A report panel: validates a `vmn-panel` spec and renders the component
 *  its type maps to, mounted only once scrolled near the viewport. */
import { useMemo, type ReactNode } from "react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { apiReports } from "../apiReports";
import LazyMount from "../components/LazyMount";
import OverlayChart from "../components/OverlayChart";
import { AUTO_X } from "../util/xMetric";
import { validate, type PanelSpec } from "./panelSpec";
import { useQueryVerstrs } from "./panelData";
import { frozenClient, LivePanelScope, type PanelPayload } from "./publishedData";
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

/** Where a published revision keeps its panels' data. */
export type PublishedRef = { rid: string; rev: number };

function PublishedBody({ ws, spec, published }: { ws: string; spec: PanelSpec; published: PublishedRef }) {
  const id = String(spec.id ?? "");
  const q = useQuery({
    queryKey: ["report-panel-data", ws, published.rid, published.rev, id],
    queryFn: () => apiReports.getPanelData(ws, published.rid, published.rev, id),
    staleTime: Infinity,
  });
  if (q.error) return <NoData />;
  if (!q.data) return <div className="muted">Loading…</div>;
  return <FrozenBody ws={ws} spec={spec} payload={q.data as PanelPayload} />;
}

const NoData = () => <div className="muted">No published data for this panel</div>;

function FrozenBody({ ws, spec, payload }: { ws: string; spec: PanelSpec; payload: PanelPayload }) {
  const client = useMemo(() => frozenClient(payload), [payload]);
  return <QueryClientProvider client={client}>{body(ws, spec)}</QueryClientProvider>;
}

/** An exported panel: renders from its inlined payload (null = none). */
function InlinedBody({ spec, payload }: { spec: PanelSpec; payload: PanelPayload | null }) {
  return payload ? <FrozenBody ws={payload.ws ?? ""} spec={spec} payload={payload} /> : <NoData />;
}

function LiveBody({ ws, spec }: { ws: string; spec: PanelSpec }) {
  return <LivePanelScope id={String(spec.id ?? "")} ws={ws} app={spec.app}>{body(ws, spec)}</LivePanelScope>;
}

function PanelBody({ ws, spec, published, payload }: {
  ws: string; spec: PanelSpec; published?: PublishedRef; payload?: PanelPayload | null;
}) {
  if (payload !== undefined) return <InlinedBody spec={spec} payload={payload} />;
  return published ? <PublishedBody ws={ws} spec={spec} published={published} /> : <LiveBody ws={ws} spec={spec} />;
}

export default function Panel({ ws, spec, published, payload }: {
  ws: string; spec: unknown; published?: PublishedRef; payload?: PanelPayload | null;
}) {
  const result = validate(spec);
  if (!result.ok) return <PanelError message={result.error} />;
  const s = result.spec;
  return (
    <div className="md-panel" data-panel-id={s.id}>
      {s.title && <div className="eyebrow">{s.title}</div>}
      <LazyMount height={s.height ?? DEFAULT_HEIGHT}>
        <PanelBody ws={ws} spec={s} published={published} payload={payload} />
      </LazyMount>
    </div>
  );
}
