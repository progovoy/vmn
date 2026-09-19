import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import type { ExperimentDetail, SeriesPoint } from "../types";
import { seriesColor } from "../util";
import SmoothingSlider from "../components/SmoothingSlider";
import { ema } from "../hooks/useSmoothing";
import { Skeleton } from "../components/ui";

type XMode = "step" | "wall" | "relative";

function fmtWallTick(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function fmtRelTick(secs: number): string {
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  return `${Math.round(secs / 3600)}h`;
}

/** Find metrics that have series data in every fetched experiment. */
function sharedMetrics(details: ExperimentDetail[]): string[] {
  if (details.length === 0) return [];
  const sets = details.map((d) => new Set(
    Object.keys(d.series).filter((m) => d.series[m].length > 1)
  ));
  return [...sets[0]].filter((m) => sets.every((s) => s.has(m))).sort();
}

/** Build per-metric chart data: each row has { x, "verstr1": val, "verstr2": val, ... } */
function buildChartData(
  metric: string,
  details: ExperimentDetail[],
  runs: string[],
  xMode: XMode,
): Record<string, number>[] {
  let firstTs = Infinity;
  if (xMode !== "step") {
    for (const d of details) {
      for (const p of d.series[metric] ?? []) {
        if (p.ts) {
          const t = new Date(p.ts).getTime();
          if (t < firstTs) firstTs = t;
        }
      }
    }
  }

  const byX = new Map<number, Record<string, number>>();
  details.forEach((d, ri) => {
    const verstr = runs[ri];
    (d.series[metric] ?? []).forEach((p: SeriesPoint, i: number) => {
      let x: number;
      if (xMode === "wall" && p.ts) {
        x = new Date(p.ts).getTime();
      } else if (xMode === "relative" && p.ts) {
        x = (new Date(p.ts).getTime() - firstTs) / 1000;
      } else {
        x = p.step ?? i;
      }
      const row = byX.get(x) ?? { x };
      row[verstr] = p.value;
      byX.set(x, row);
    });
  });
  return [...byX.values()].sort((a, b) => a.x - b.x);
}

export default function Overlay() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [searchParams] = useSearchParams();
  const runs = useMemo(() => {
    const raw = searchParams.get("runs") ?? "";
    return raw ? raw.split(",").filter(Boolean) : [];
  }, [searchParams]);

  const [details, setDetails] = useState<ExperimentDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alpha, setAlpha] = useState(0);
  const [xMode, setXMode] = useState<XMode>("step");

  useEffect(() => {
    if (runs.length === 0) return;
    Promise.all(runs.map((v) => api.experiment(ws, app, v)))
      .then(setDetails)
      .catch((e) => setError(String(e)));
  }, [ws, app, runs]);

  const metrics = useMemo(
    () => (details ? sharedMetrics(details) : []),
    [details],
  );

  const hasTimestamps = useMemo(() => {
    if (!details) return false;
    return details.every((d) =>
      Object.values(d.series).every((pts) => pts.every((p) => p.ts != null))
    );
  }, [details]);

  if (runs.length === 0) {
    return (
      <>
        <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
          ← experiments
        </Link>
        <div className="empty">No runs selected. Select runs from the leaderboard to overlay their training curves.</div>
      </>
    );
  }

  if (error) return <div className="error">{error}</div>;
  if (!details) return <Skeleton />;

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
        ← experiments
      </Link>
      <div className="page-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 style={{ fontSize: 20 }}>Overlay — {runs.length} runs</h1>
      </div>

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
            <span
              key={v}
              style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-2)" }}
            >
              <span
                style={{
                  width: 14, height: 3, borderRadius: 2,
                  background: seriesColor(runs, v),
                }}
              />
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
            details={details}
            runs={runs}
            alpha={alpha}
            xMode={xMode}
          />
        ))
      )}
    </>
  );
}

function MetricChart({ metric, details, runs, alpha, xMode }: {
  metric: string;
  details: ExperimentDetail[];
  runs: string[];
  alpha: number;
  xMode: XMode;
}) {
  const points = useMemo(
    () => buildChartData(metric, details, runs, xMode),
    [metric, details, runs, xMode],
  );

  const smoothedPoints = useMemo(() => {
    if (alpha === 0 || points.length === 0) return points;
    const result = points.map((p) => ({ ...p }));
    for (const v of runs) {
      const raw = points.map((p) => (p[v] as number) ?? NaN);
      const sm = ema(raw, alpha);
      sm.forEach((val, i) => {
        (result[i] as Record<string, number>)[`${v}__smooth`] = val;
      });
    }
    return result;
  }, [points, alpha, runs]);

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="eyebrow" style={{ marginBottom: 10 }}>{metric}</div>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={smoothedPoints}>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis
            dataKey="x"
            stroke="#85847a"
            tick={{ fontSize: 10.5, fontFamily: "var(--mono)" }}
            tickFormatter={
              xMode === "wall" ? fmtWallTick
                : xMode === "relative" ? fmtRelTick
                : undefined
            }
          />
          <YAxis
            stroke="#85847a"
            width={60}
            tick={{ fontSize: 10.5, fontFamily: "var(--mono)" }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--panel-2)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              color: "var(--text)",
            }}
          />
          {runs.map((v) => (
            <Fragment key={v}>
              {alpha > 0 && (
                <Line
                  type="monotone"
                  dataKey={v}
                  stroke={seriesColor(runs, v)}
                  strokeWidth={1}
                  strokeOpacity={0.3}
                  strokeDasharray="4 2"
                  dot={false}
                  isAnimationActive={false}
                  name={`${v} (raw)`}
                />
              )}
              <Line
                type="monotone"
                dataKey={alpha > 0 ? `${v}__smooth` : v}
                stroke={seriesColor(runs, v)}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                name={alpha > 0 ? `${v} (smooth)` : v}
              />
            </Fragment>
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
