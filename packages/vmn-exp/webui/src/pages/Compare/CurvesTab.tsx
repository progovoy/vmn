import { useCallback, useMemo, useState } from "react";
import { runColor } from "../../util";
import { allTimestamped } from "../../util/chartData";
import { LogToggle } from "../../components/ChartControls";
import XAxisControl from "../../components/XAxisControl";
import { useCurveControls } from "../../hooks/useCurveControls";
import OverlayChart from "../../components/OverlayChart";
import OverlayLegend from "../../components/OverlayLegend";
import SmoothingSlider from "../../components/SmoothingSlider";
import { Skeleton } from "../../components/ui";
import AddToReport from "../../reports/AddToReport";
import { overlaySpec } from "../../reports/viewSpecs";
import OverlayNoCurves, { TrialLinks } from "../../components/OverlayNoCurves";
import { useOverlaySeries } from "../overlaySeries";
import { curvelessRuns, unionMetrics } from "../overlayCoverage";
import { runText } from "../../shell/crumbs";

/** More runs than this make an unreadable chart and a lot of payload. */
export const MAX_OVERLAY_RUNS = 100;

/** The selected runs' training curves overlaid, one chart per metric. */
export default function CurvesTab({ ws, app, refs }: { ws: string; app: string; refs: string[] }) {
  const runs = useMemo(() => refs.slice(0, MAX_OVERLAY_RUNS), [refs]);

  const { data, error } = useOverlaySeries(ws, app, runs);
  const {
    smoothing: alpha, setSmoothing: setAlpha, xMode, setXMode, x: xChoice, setX: setXChoice, logY, setLogY,
  } = useCurveControls({});
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);

  const loaded = useMemo(() => data?.runs ?? [], [data]);
  const metrics = useMemo(() => unionMetrics(loaded), [loaded]);
  const legendKeys = useMemo(() => {
    const none = new Set(curvelessRuns(loaded).map((r) => r.key));
    return loaded.map((r) => r.key).filter((k) => !none.has(k));
  }, [loaded]);
  const hasTimestamps = useMemo(
    () => loaded.length > 0 && loaded.every((r) => allTimestamped(r.series)), [loaded],
  );
  const colorOf = useMemo(() => {
    const idx = new Map(runs.map((v, i) => [v, i]));
    return (key: string) => runColor(idx.get(key) ?? 0);
  }, [runs]);
  const labelOf = useMemo(() => {
    const byKey = new Map(loaded.map((r) => [r.key, runText({ verstr: r.key, idx: r.idx ?? null, name: r.name ?? null })]));
    return (key: string) => byKey.get(key) ?? key;
  }, [loaded]);
  const toggle = useCallback((v: string) => setHidden((prev) => {
    const next = new Set(prev);
    if (!next.delete(v)) next.add(v);
    return next;
  }), []);

  if (runs.length === 0) {
    return <div className="empty">No runs selected. Select runs from the leaderboard to overlay their training curves.</div>;
  }

  if (error && !data) return <div className="error">{error}</div>;
  if (!data) return <Skeleton />;

  return (
    <>
      {metrics.length > 0 && (
        <div className="toolbar" style={{ marginBottom: 6 }}>
          <span className="spacer" />
          <AddToReport ws={ws} spec={() => overlaySpec({
            app, verstrs: runs, keys: metrics, smoothing: alpha, xMode, x: xChoice, logY,
          })} />
        </div>
      )}
      {refs.length > runs.length && (
        <p style={{ color: "var(--text-2)", margin: "0 0 12px" }}>
          showing the first {runs.length} of {refs.length} selected runs
        </p>
      )}
      {data.missing.length > 0 && (
        <p style={{ color: "var(--text-3)", margin: "0 0 12px" }}>not found: {data.missing.join(", ")}</p>
      )}

      {metrics.length > 0 && <OverlayNoCurves ws={ws} app={app} runs={loaded} />}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <XAxisControl
          xMode={xMode} x={xChoice} metrics={metrics} timeEnabled={hasTimestamps}
          onXMode={setXMode} onX={setXChoice}
        />
        <LogToggle value={logY} onChange={setLogY} />
        <SmoothingSlider value={alpha} onChange={setAlpha} />
        <OverlayLegend
          runs={legendKeys} colorOf={colorOf} labelOf={labelOf} hidden={hidden}
          onToggle={toggle} onHover={setFocused}
        />
      </div>

      {metrics.length === 0 ? (
        <div className="empty">
          None of the selected runs has series data.
          <TrialLinks ws={ws} app={app} runs={loaded} />
        </div>
      ) : (
        <OverlayChart
          ws={ws} app={app} verstrs={runs} keys={metrics} x={xChoice} smoothing={alpha}
          xMode={xMode} logY={logY} hidden={hidden} focused={focused} data={data}
        />
      )}
    </>
  );
}
