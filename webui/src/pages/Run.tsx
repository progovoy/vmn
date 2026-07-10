import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import type { ExperimentDetail, LogEntry } from "../types";
import { fmtVal, relTime, seriesColor } from "../util";
import { AppLayoutNav } from "./Leaderboard";

function describeEntry(e: LogEntry): string {
  switch (e.type) {
    case "create":
      return `created${e.note ? `: ${e.note}` : ""}`;
    case "metrics": {
      const values = (e.values ?? {}) as Record<string, unknown>;
      const step = e.step !== undefined ? `step ${e.step} — ` : "";
      return `${step}${Object.entries(values)
        .map(([k, v]) => `${k}=${fmtVal(v as number)}`)
        .join(", ")}`;
    }
    case "note":
      return `note: ${e.text}`;
    case "artifact":
      return `artifact: ${e.path} (${e.size} bytes)`;
    case "run":
      return `ran \`${(e.command as string[]).join(" ")}\` — exit ${e.exit_code} in ${e.duration_sec}s`;
    default:
      return e.type;
  }
}

export default function Run() {
  const { ws, app, verstr } = useParams() as {
    ws: string; app: string; verstr: string;
  };
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.experiment(ws, app, verstr).then(setDetail).catch((e) => setError(String(e)));
  }, [ws, app, verstr]);

  const chartData = useMemo(() => {
    if (!detail) return { points: [], metrics: [] as string[] };
    const metrics = Object.keys(detail.series).filter(
      (m) => detail.series[m].length > 1
    );
    const byX = new Map<number, Record<string, number>>();
    metrics.forEach((m) =>
      detail.series[m].forEach((p, i) => {
        const x = p.step ?? i;
        const row = byX.get(x) ?? { x };
        row[m] = p.value;
        byX.set(x, row as Record<string, number>);
      })
    );
    const points = [...byX.values()].sort((a, b) => a.x - b.x);
    return { points, metrics };
  }, [detail]);

  if (error) return <div className="error">{error}</div>;
  if (!detail) return <div className="empty">Loading…</div>;

  const meta = detail.metadata;
  const appName = app.replaceAll("-", "/");

  return (
    <>
      <h1 className="mono">{meta.verstr}</h1>
      <AppLayoutNav />

      <div className="card">
        <div className="kv">
          <div className="k">note</div>
          <div>{(meta.note as string) ?? "–"}</div>
          <div className="k">branch</div>
          <div className="mono">{meta.branch as string}</div>
          <div className="k">base</div>
          <div className="mono">
            {meta.base_version as string} ({(meta.base_commit as string)?.slice(0, 7)})
          </div>
          <div className="k">created</div>
          <div>{relTime(meta.timestamp as string)}</div>
          <div className="k">captured</div>
          <div>
            {Object.entries(detail.patches)
              .filter(([, v]) => v)
              .map(([k]) => k.replaceAll("_", " "))
              .join(", ") || "clean tree"}
          </div>
        </div>
      </div>

      {Object.keys(detail.metrics).length > 0 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>metrics</h2>
          <div className="kv">
            {Object.entries(detail.metrics).map(([k, v]) => (
              <FragmentRow key={k} k={k} v={fmtVal(v)} />
            ))}
          </div>
        </div>
      )}

      {chartData.metrics.length > 0 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>training curves</h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData.points}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="x" stroke="var(--text-muted)" name="step" />
              <YAxis stroke="var(--text-muted)" width={60} />
              <Tooltip
                contentStyle={{
                  background: "var(--surface-2)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              {chartData.metrics.length > 1 && <Legend />}
              {chartData.metrics.map((m) => (
                <Line
                  key={m}
                  type="monotone"
                  dataKey={m}
                  stroke={seriesColor(chartData.metrics, m)}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>log</h2>
        <ul className="timeline">
          {detail.log.map((e, i) => (
            <li key={i}>
              <span className="ts">{relTime(e.timestamp)}</span>
              <span>{describeEntry(e)}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>reproduce</h2>
        <div className="cli-hint">
          vmn exp restore {appName} -v {meta.verstr}{"\n"}
          vmn exp export {appName} -v {meta.verstr}
        </div>
      </div>
    </>
  );
}

function FragmentRow({ k, v }: { k: string; v: string }) {
  return (
    <>
      <div className="k">{k}</div>
      <div className="metric">{v}</div>
    </>
  );
}
