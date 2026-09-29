import { memo, useCallback, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { runColor } from "../util";
import { allTimestamped, type XMode } from "../util/chartData";
import type { CurveSeries } from "../util/curveOptions";
import { emaXY, toXY } from "../util/seriesArrays";
import { LogToggle, XMetricSelect, XModeToggle } from "../components/ChartControls";
import { fetchSeriesBatch } from "../apiSeries";
import { useJoinedSeries } from "../hooks/useJoinedSeries";
import type { SeriesPoint } from "../types";
import { AUTO_X, xMetricLabel, xMetricMap, type XMap } from "../util/xMetric";
import CurveChart from "../components/CurveChart";
import LazyMount from "../components/LazyMount";
import OverlayLegend from "../components/OverlayLegend";
import SmoothingSlider from "../components/SmoothingSlider";
import { Skeleton } from "../components/ui";
import { OVERLAY_POINTS, useOverlaySeries, type OverlayRunData } from "./overlaySeries";

type Joined = Record<string, Record<string, SeriesPoint[]>>;

/** More runs than this make an unreadable chart and a lot of payload. */
export const MAX_OVERLAY_RUNS = 100;
const CHART_H = 260;

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
  const [alpha, setAlpha] = useState(0);
  const [xMode, setXMode] = useState<XMode>("step");
  const [xChoice, setXChoice] = useState(AUTO_X);
  const [logY, setLogY] = useState(false);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);

  const loaded = useMemo(() => data?.runs ?? [], [data]);
  const loadedKeys = useMemo(() => loaded.map((r) => r.key), [loaded]);
  const metrics = useMemo(() => sharedMetrics(loaded), [loaded]);
  const xMap = useMemo(
    () => xMetricMap(metrics, xMode, xChoice, data?.stepMetrics), [metrics, xMode, xChoice, data],
  );
  const fetchJoined = useCallback(
    (x: XMap) => fetchSeriesBatch(ws, app, loadedKeys, Object.keys(x), OVERLAY_POINTS, x)
      .then((b) => b.series),
    [ws, app, loadedKeys],
  );
  const { data: joined, error: joinError } = useJoinedSeries<Joined>(xMap, fetchJoined, data);
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
      {joinError && <div className="error">{joinError.message}</div>}

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
        metrics.map((metric) => (
          <div key={metric} className="card" style={{ marginBottom: 16 }}>
            <div className="eyebrow" style={{ marginBottom: 10 }}>{metric}</div>
            <LazyMount height={CHART_H}>
              <OverlayChart
                metric={metric} runs={loaded} colorOf={colorOf} xMode={xMode}
                xMetric={joined ? xMap[metric] ?? null : null} joined={joined}
                alpha={alpha} logY={logY} hidden={hidden} focused={focused}
              />
            </LazyMount>
          </div>
        ))
      )}
    </>
  );
}

/** One metric across runs. Each run keeps its own typed x/y arrays, and
 *  "relative" x is measured from each run's own start. With many runs the
 *  smoothed curve replaces the raw one rather than doubling the lines. */
const OverlayChart = memo(function OverlayChart({
  metric, runs, colorOf, xMode: plainMode, xMetric, joined, alpha, logY, hidden, focused,
}: {
  metric: string;
  runs: OverlayRunData[];
  colorOf: (key: string) => string;
  xMode: XMode;
  /** Plot against this metric, from *joined*, instead of *xMode*. */
  xMetric: string | null;
  joined: Joined | null;
  alpha: number;
  logY: boolean;
  hidden: ReadonlySet<string>;
  focused: string | null;
}) {
  const xMode = xMetric ? "metric" : plainMode;
  const raw = useMemo(
    () => runs.map((r) => {
      const points = (xMetric ? joined?.[r.key] : r.series)?.[metric] ?? [];
      return { key: r.key, ...toXY(points, xMode, r.origin, { positiveOnly: logY }) };
    }),
    [metric, runs, xMode, xMetric, joined, logY],
  );
  const formatX = useMemo(() => (xMetric ? xMetricLabel(xMetric) : undefined), [xMetric]);
  const series = useMemo<CurveSeries[]>(
    () => raw.map((r) => ({ ...r, label: r.key, color: colorOf(r.key), ys: emaXY(r.ys, alpha) })),
    [raw, colorOf, alpha],
  );
  return (
    <CurveChart
      series={series} xMode={xMode} logY={logY} height={CHART_H}
      hidden={hidden} focused={focused} formatX={formatX}
    />
  );
});
