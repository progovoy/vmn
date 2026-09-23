import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { ExperimentDetail } from "../types";
import { runColor } from "../util";
import {
  allTimestamped, capSeries, overlayRows, runOrigin, type OverlayRun, type XMode,
} from "../util/chartData";
import SmoothingSlider from "../components/SmoothingSlider";
import CurveChart from "../components/CurveChart";
import { Skeleton } from "../components/ui";

/** More runs than this make an unreadable chart and a lot of payload. */
export const MAX_OVERLAY_RUNS = 20;
/** Per-metric point budget per run once several runs share a chart. */
const OVERLAY_POINTS = 1000;

/** Metrics that have series data in every fetched experiment. */
function sharedMetrics(details: ExperimentDetail[]): string[] {
  if (details.length === 0) return [];
  const sets = details.map((d) => new Set(
    Object.keys(d.series).filter((m) => d.series[m].length > 1)
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

  const [details, setDetails] = useState<ExperimentDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alpha, setAlpha] = useState(0);
  const [xMode, setXMode] = useState<XMode>("step");

  useEffect(() => {
    if (runs.length === 0) return;
    Promise.all(runs.map((v) => api.experiment(ws, app, v, OVERLAY_POINTS)))
      .then(setDetails)
      .catch((e) => setError(String(e)));
  }, [ws, app, runs]);

  // Each run is placed on its own clock: "relative" is time since that run's start.
  const overlayRuns = useMemo<OverlayRun[]>(
    () => (details ?? []).map((d, i) => {
      const series = capSeries(d.series, OVERLAY_POINTS);
      return { key: runs[i], series, origin: runOrigin(series, d.status?.started_at) };
    }),
    [details, runs],
  );
  const metrics = useMemo(() => (details ? sharedMetrics(details) : []), [details]);
  const hasTimestamps = useMemo(
    () => overlayRuns.length > 0 && overlayRuns.every((r) => allTimestamped(r.series)),
    [overlayRuns],
  );
  const colorOf = useMemo(() => {
    const idx = new Map(runs.map((v, i) => [v, i]));
    return (key: string) => runColor(idx.get(key.replace(/__smooth$/, "")) ?? 0);
  }, [runs]);

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

  if (error) return <div className="error">{error}</div>;
  if (!details) return <Skeleton />;

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

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 2, fontSize: 11 }}>
          {(["step", "wall", "relative"] as const).map((mode) => (
            <button
              key={mode}
              className={xMode === mode ? "primary" : ""}
              style={{ padding: "2px 8px", fontSize: 11, borderRadius: 4 }}
              disabled={mode !== "step" && !hasTimestamps}
              onClick={() => setXMode(mode)}
            >
              {mode === "step" ? "Step" : mode === "wall" ? "Wall" : "Relative"}
            </button>
          ))}
        </div>
        <SmoothingSlider value={alpha} onChange={setAlpha} />
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 12, flexWrap: "wrap" }}>
          {runs.map((v) => (
            <span key={v} style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-2)" }}>
              <span style={{ width: 14, height: 3, borderRadius: 2, background: colorOf(v) }} />
              {v}
            </span>
          ))}
        </div>
      </div>

      {metrics.length === 0 ? (
        <div className="empty">No shared metrics with series data across the selected runs.</div>
      ) : (
        metrics.map((metric) => (
          <MetricChart
            key={metric}
            metric={metric}
            runs={overlayRuns}
            keys={runs}
            colorOf={colorOf}
            alpha={alpha}
            xMode={xMode}
          />
        ))
      )}
    </>
  );
}

function MetricChart({ metric, runs, keys, colorOf, alpha, xMode }: {
  metric: string;
  runs: OverlayRun[];
  keys: string[];
  colorOf: (key: string) => string;
  alpha: number;
  xMode: XMode;
}) {
  const rows = useMemo(() => overlayRows(metric, runs, xMode), [metric, runs, xMode]);
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="eyebrow" style={{ marginBottom: 10 }}>{metric}</div>
      <CurveChart rows={rows} keys={keys} colorOf={colorOf} alpha={alpha} xMode={xMode} height={260} />
    </div>
  );
}
