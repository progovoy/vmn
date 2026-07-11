import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, appName as toAppName } from "../api";
import type { ExperimentDetail, LogEntry, MetricsSchema } from "../types";
import { fmtVal, metricGoal, relTime, seriesColor } from "../util";
import { JobCard, Skeleton, useJob } from "../components/ui";

/** Inline `vmn experiment add -v <verstr> --metrics …` — append more metric
 *  points to this run. Latest value wins in the summary; every point is kept
 *  for the training-curve chart. */
function AppendMetrics({ ws, app, verstr, onAdded }: {
  ws: string; app: string; verstr: string; onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const { job, error, run } = useJob((j) => {
    if (j.status === "succeeded") {
      setText("");
      setOpen(false);
      onAdded();
    }
  });

  const submit = () => {
    const metrics: Record<string, string> = {};
    for (const pair of text.trim().split(/\s+/).filter(Boolean)) {
      const eq = pair.indexOf("=");
      if (eq < 1) {
        setParseError(`"${pair}" is not key=value`);
        return;
      }
      metrics[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    if (Object.keys(metrics).length === 0) {
      setParseError("enter at least one key=value");
      return;
    }
    setParseError(null);
    run(ws, app, "exp_add", { verstr, metrics });
  };

  if (!open) {
    return (
      <button
        className="link"
        style={{ marginTop: 12 }}
        onClick={() => setOpen(true)}
      >
        ＋ append metrics
      </button>
    );
  }

  const running = job?.status === "running";
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <label className="field">
        add metrics (key=value, space-separated)
        <input
          className="mono"
          placeholder="loss=0.09 acc=0.95"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoFocus
        />
      </label>
      <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
        <button className="primary" onClick={submit} disabled={running}>
          {running ? "Adding…" : "Append"}
        </button>
        <button onClick={() => { setOpen(false); setParseError(null); }}>Cancel</button>
        {(parseError || error) && <span className="error">{parseError || error}</span>}
      </div>
      {job && job.status === "failed" && <JobCard job={job} />}
    </div>
  );
}

const DOT_COLOR: Record<string, string> = {
  create: "var(--accent)",
  run: "var(--good)",
  metrics: "var(--text-3)",
  note: "var(--pre)",
  artifact: "var(--hotfix)",
};

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
  const [schema, setSchema] = useState<MetricsSchema | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () => api.experiment(ws, app, verstr).then(setDetail).catch((e) => setError(String(e))),
    [ws, app, verstr]
  );
  useEffect(() => {
    load();
    api.metricsSchema(ws, app).then(setSchema).catch(() => setSchema({}));
  }, [load, ws, app]);

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
  if (!detail) return <Skeleton />;

  const meta = detail.metadata;
  const appName = toAppName(app);
  const captured =
    Object.entries(detail.patches)
      .filter(([, v]) => v)
      .map(([k]) => k.replaceAll("_", " "))
      .join(", ") || "clean tree";
  const runSecs = detail.log
    .filter((e) => e.type === "run")
    .reduce((s, e) => s + (Number(e.duration_sec) || 0), 0);

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
        ← experiments
      </Link>
      <div className="page-head" style={{ alignItems: "center", marginBottom: 6 }}>
        <h1 className="mono" style={{ fontSize: 20 }}>{meta.verstr}</h1>
        {Boolean(meta.branch) && <span className="badge">{meta.branch as string}</span>}
      </div>
      {Boolean(meta.note) && (
        <p style={{ color: "var(--text-2)", margin: "0 0 20px" }}>
          {meta.note as string}
        </p>
      )}

      <div className="card-grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="eyebrow">metadata</div>
          <div className="kv">
            <div className="k">branch</div>
            <div className="mono">{meta.branch as string}</div>
            <div className="k">base</div>
            <div className="mono">
              {meta.base_version as string} ({(meta.base_commit as string)?.slice(0, 7)})
            </div>
            <div className="k">created</div>
            <div title={meta.timestamp as string}>{relTime(meta.timestamp as string)}</div>
            <div className="k">captured</div>
            <div style={{ color: "var(--text-2)" }}>{captured}</div>
            <div className="k">runtime</div>
            <div>{runSecs ? `${runSecs}s` : "—"}</div>
          </div>
        </div>
        <div className="card">
          <div className="eyebrow">final metrics</div>
          {Object.keys(detail.metrics).length === 0 ? (
            <div className="empty" style={{ padding: 12 }}>No metrics logged.</div>
          ) : (
            <div>
              {Object.entries(detail.metrics).map(([k, v]) => {
                const goal = metricGoal(schema, k);
                const isPrimary = Boolean(schema?.[k]?.primary);
                return (
                  <div
                    key={k}
                    style={{
                      display: "flex", alignItems: "center",
                      justifyContent: "space-between", padding: "7px 0",
                      borderBottom: "1px solid var(--line)",
                    }}
                  >
                    <span style={{ color: "var(--text-2)", fontSize: 13 }}>
                      {k}{" "}
                      {typeof v === "number" && (
                        <span style={{ color: "var(--text-3)", fontSize: 11 }}>
                          {goal === "min" ? "↓" : "↑"}
                        </span>
                      )}
                    </span>
                    <span className={`metric${isPrimary ? " best" : ""}`}>
                      {fmtVal(v)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          <AppendMetrics ws={ws} app={app} verstr={meta.verstr as string} onAdded={load} />
        </div>
      </div>

      {chartData.metrics.length > 0 && (
        <div className="card">
          <div
            style={{
              display: "flex", alignItems: "center",
              justifyContent: "space-between", marginBottom: 14,
            }}
          >
            <div className="eyebrow" style={{ marginBottom: 0 }}>training curves</div>
            <div style={{ display: "flex", gap: 16, fontSize: 12 }}>
              {chartData.metrics.map((m) => (
                <span
                  key={m}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    color: "var(--text-2)",
                  }}
                >
                  <span
                    style={{
                      width: 14, height: 3, borderRadius: 2,
                      background: seriesColor(chartData.metrics, m),
                    }}
                  />
                  {m}
                </span>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData.points}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis
                dataKey="x"
                stroke="#85847a"
                tick={{ fontSize: 10.5, fontFamily: "var(--mono)" }}
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
              {chartData.metrics.map((m) => (
                <Line
                  key={m}
                  type="monotone"
                  dataKey={m}
                  stroke={seriesColor(chartData.metrics, m)}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card-grid-wide">
        <div className="card">
          <div className="eyebrow">log</div>
          <ul className="timeline">
            {detail.log.map((e, i) => (
              <li
                key={i}
                style={{ "--dot": DOT_COLOR[e.type] ?? "var(--text-3)" } as React.CSSProperties}
              >
                <span className="ts">{relTime(e.timestamp)}</span>
                <span className="what">{describeEntry(e)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <div className="eyebrow">reproduce</div>
          <div className="cli-hint">
            vmn exp restore {appName} -v {meta.verstr}
          </div>
          <div className="cli-hint">
            vmn exp export {appName} -v {meta.verstr}
          </div>
        </div>
      </div>
    </>
  );
}
