import { useCallback, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { runColor } from "../util";
import { allTimestamped } from "../util/chartData";
import { LogToggle, XMetricSelect, XModeToggle } from "../components/ChartControls";
import { useCurveControls } from "../hooks/useCurveControls";
import OverlayChart from "../components/OverlayChart";
import OverlayLegend from "../components/OverlayLegend";
import SmoothingSlider from "../components/SmoothingSlider";
import { Skeleton } from "../components/ui";
import { useOverlaySeries, type OverlayRunData } from "./overlaySeries";

/** More runs than this make an unreadable chart and a lot of payload. */
export const MAX_OVERLAY_RUNS = 100;

/** Metrics that have series data in every fetched run. */
function sharedMetrics(runs: OverlayRunData[]): string[] {
  if (runs.length === 0) return [];
  const sets = runs.map((r) => new Set(
    Object.keys(r.series).filter((m) => r.series[m].length > 1),
  ));
  return [...sets[0]].filter((m) => sets.every((s) => s.has(m))).sort();
}

export default function Overlay() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [searchParams] = useSearchParams();
  const requested = useMemo(() => {
    const raw = searchParams.get("runs") ?? "";
    return raw ? raw.split(",").filter(Boolean) : [];
  }, [searchParams]);
  const runs = useMemo(() => requested.slice(0, MAX_OVERLAY_RUNS), [requested]);

  const { data, error } = useOverlaySeries(ws, app, runs);
  const {
    smoothing: alpha, setSmoothing: setAlpha, xMode, setXMode, x: xChoice, setX: setXChoice, logY, setLogY,
  } = useCurveControls({});
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);

  const loaded = useMemo(() => data?.runs ?? [], [data]);
  const loadedKeys = useMemo(() => loaded.map((r) => r.key), [loaded]);
  const metrics = useMemo(() => sharedMetrics(loaded), [loaded]);
  const hasTimestamps = useMemo(
    () => loaded.length > 0 && loaded.every((r) => allTimestamped(r.series)), [loaded],
  );
  const colorOf = useMemo(() => {
    const idx = new Map(runs.map((v, i) => [v, i]));
    return (key: string) => runColor(idx.get(key) ?? 0);
  }, [runs]);
  const toggle = useCallback((v: string) => setHidden((prev) => {
    const next = new Set(prev);
    if (!next.delete(v)) next.add(v);
    return next;
  }), []);

  const back = (
    <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
      ← experiments
    </Link>
  );

  if (runs.length === 0) {
    return (
      <>
        {back}
        <div className="empty">No runs selected. Select runs from the leaderboard to overlay their training curves.</div>
      </>
    );
  }

  if (error && !data) return <div className="error">{error}</div>;
  if (!data) return <Skeleton />;

  return (
    <>
      {back}
      <div className="page-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 style={{ fontSize: 20 }}>Overlay — {runs.length} runs</h1>
      </div>
      {requested.length > runs.length && (
        <p style={{ color: "var(--text-2)", margin: "0 0 12px" }}>
          showing the first {runs.length} of {requested.length} selected runs
        </p>
      )}
      {data.missing.length > 0 && (
        <p style={{ color: "var(--text-3)", margin: "0 0 12px" }}>not found: {data.missing.join(", ")}</p>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <XModeToggle value={xMode} onChange={setXMode} timeEnabled={hasTimestamps} />
        <XMetricSelect value={xChoice} onChange={setXChoice} metrics={metrics} enabled={xMode === "step"} />
        <LogToggle value={logY} onChange={setLogY} />
        <SmoothingSlider value={alpha} onChange={setAlpha} />
        <OverlayLegend
          runs={loadedKeys} colorOf={colorOf} hidden={hidden}
          onToggle={toggle} onHover={setFocused}
        />
      </div>

      {metrics.length === 0 ? (
        <div className="empty">No shared metrics with series data across the selected runs.</div>
      ) : (
        <OverlayChart
          ws={ws} app={app} verstrs={runs} keys={metrics} x={xChoice} smoothing={alpha}
          xMode={xMode} logY={logY} hidden={hidden} focused={focused} data={data}
        />
      )}
    </>
  );
}
