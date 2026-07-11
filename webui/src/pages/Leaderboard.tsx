import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, appName as toAppName } from "../api";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, relTime, seriesColor } from "../util";
import { JobCard, PageHead, Skeleton, useJob } from "../components/ui";

/** One small chart per metric — each on its own scale, so a loss (~0.1) and
 *  an accuracy (~0.9) don't get squashed onto a shared axis. Same visual
 *  language as the run-detail training curves, in a small-multiples grid. */
function ParamPlots({ rows, metricCols, schema }: {
  rows: ExperimentRow[]; metricCols: string[]; schema: MetricsSchema | null;
}) {
  const plotCols = useMemo(
    () => metricCols.filter(
      (m) => rows.filter((r) => typeof r.metrics[m] === "number").length > 1
    ),
    [rows, metricCols]
  );
  const points = useMemo(
    () => [...rows].sort((a, b) => a.idx - b.idx),
    [rows]
  );

  if (plotCols.length === 0) return null;

  return (
    <div className="card">
      <div className="eyebrow">metrics across runs</div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
        gap: 20,
      }}>
        {plotCols.map((m) => {
          const { goal, known } = metricGoal(schema, m);
          const color = seriesColor(plotCols, m);
          const data = points.map((r) => ({ x: r.idx, v: r.metrics[m] as number | undefined }));
          const vals = data.map((d) => d.v).filter((v): v is number => typeof v === "number");
          const best = vals.length
            ? (goal === "min" ? Math.min(...vals) : Math.max(...vals))
            : null;
          return (
            <div key={m}>
              <div style={{
                display: "flex", alignItems: "baseline", justifyContent: "space-between",
                marginBottom: 6, fontSize: 12,
              }}>
                <span className="mono" style={{ color: "var(--text-2)" }}>
                  {m}{" "}
                  {known && <span style={{ color: "var(--text-3)" }}>{goal === "min" ? "↓" : "↑"}</span>}
                </span>
                {best !== null && (
                  <span style={{ color: "var(--good)", fontSize: 11 }}>best {fmtVal(best)}</span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={110}>
                <LineChart data={data}>
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="x" hide />
                  <YAxis
                    width={34} stroke="#85847a"
                    tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
                  />
                  <Tooltip
                    labelFormatter={(x) => `@${x}`}
                    formatter={(v: number) => fmtVal(v)}
                    contentStyle={{
                      background: "var(--panel-2)",
                      border: "1px solid var(--line)",
                      borderRadius: 8,
                      color: "var(--text)",
                      fontSize: 12,
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="v"
                    stroke={color}
                    strokeWidth={2}
                    dot={{ r: 2.5 }}
                    connectNulls
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Inline `vmn exp create` — note + metrics, run as a streamed job. */
function NewExperiment({ ws, app, appName, onCreated, onClose }: {
  ws: string; app: string; appName: string;
  onCreated: () => void; onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const [metricsText, setMetricsText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const { job, error, run } = useJob((j) => {
    if (j.status === "succeeded") onCreated();
  });

  const parseMetrics = (): Record<string, string> | null => {
    const out: Record<string, string> = {};
    for (const pair of metricsText.trim().split(/\s+/).filter(Boolean)) {
      const eq = pair.indexOf("=");
      if (eq < 1) {
        setParseError(`"${pair}" is not key=value`);
        return null;
      }
      out[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    setParseError(null);
    return out;
  };

  const submit = () => {
    const metrics = parseMetrics();
    if (metrics === null) return;
    run(ws, app, "exp_create", {
      note: note || undefined,
      metrics: Object.keys(metrics).length ? metrics : undefined,
    });
  };

  const running = job?.status === "running";
  const cli =
    `vmn exp create ${appName}` +
    (note ? ` --note "${note}"` : "") +
    (metricsText.trim() ? ` --metrics ${metricsText.trim()}` : "");

  return (
    <div className="card">
      <div className="eyebrow">new experiment</div>
      <p className="page-sub" style={{ marginBottom: 12 }}>
        Captures the workspace's current working state — dirty files, local
        commits, untracked files — as a reproducible experiment.
      </p>
      <div className="card-grid-2" style={{ marginBottom: 12 }}>
        <label className="field">
          note
          <input
            placeholder="swin-t + mixup 0.2"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            autoFocus
          />
        </label>
        <label className="field">
          metrics (key=value, space-separated)
          <input
            className="mono"
            placeholder="loss=0.12 acc=0.94"
            value={metricsText}
            onChange={(e) => setMetricsText(e.target.value)}
          />
        </label>
      </div>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <button className="primary" onClick={submit} disabled={running}>
          {running ? "Capturing…" : "Create experiment"}
        </button>
        <button onClick={onClose}>Cancel</button>
        {(parseError || error) && <span className="error">{parseError || error}</span>}
      </div>
      <div className="cli-hint">{cli}</div>
      {job && job.status === "failed" && <JobCard job={job} />}
    </div>
  );
}

export default function Leaderboard() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const appName = toAppName(app);
  const [rows, setRows] = useState<ExperimentRow[] | null>(null);
  const [schema, setSchema] = useState<MetricsSchema | null>(null);
  const [sort, setSort] = useState<string | null>(null);
  const [reversed, setReversed] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [flash, setFlash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const creating = params.get("new") === "1";
  const navigate = useNavigate();

  // Ordering comes from the server (goal-aware best-first, same code path as
  // `vmn exp list`); the client only flips the displayed direction. @N stays
  // truthful under any sort because rows carry their storage idx.
  const load = useCallback(
    () =>
      api.experiments(ws, app, sort ?? undefined)
        .then(setRows)
        .catch((e) => setError(String(e))),
    [ws, app, sort]
  );
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.metricsSchema(ws, app).then(setSchema).catch(() => setSchema({}));
  }, [ws, app]);

  const displayed = useMemo(
    () => (reversed ? [...(rows ?? [])].reverse() : rows ?? []),
    [rows, reversed]
  );

  const primary = useMemo(
    () => Object.keys(schema ?? {}).find((k) => schema![k].primary) ?? null,
    [schema]
  );
  const metricCols = useMemo(() => {
    const inData = new Set<string>();
    rows?.forEach((r) => Object.keys(r.metrics).forEach((k) => inData.add(k)));
    const fromSchema = Object.keys(schema ?? {}).filter((k) => inData.has(k));
    const extras = [...inData].filter((k) => !(schema ?? {})[k]).sort();
    return [...fromSchema, ...extras];
  }, [rows, schema]);

  // Per-column display facts, computed once per data change (not per cell).
  const colMeta = useMemo(() => {
    const meta: Record<string, {
      goal: "min" | "max"; known: boolean; best: number | null; isBar: boolean;
      min: number; max: number;
    }> = {};
    metricCols.forEach((m) => {
      const { goal, known } = metricGoal(schema, m);
      const vals = (rows ?? [])
        .map((r) => r.metrics[m])
        .filter((v): v is number => typeof v === "number");
      const min = vals.length ? Math.min(...vals) : NaN;
      const max = vals.length ? Math.max(...vals) : NaN;
      meta[m] = {
        goal, known,
        best: vals.length ? (goal === "min" ? min : max) : null,
        isBar: m === primary && vals.length > 0,
        min, max,
      };
    });
    return meta;
  }, [rows, metricCols, schema, primary]);

  const clickSort = (m: string) => {
    if (sort === m) setReversed((r) => !r);
    else {
      setSort(m);
      setReversed(false);
    }
  };

  const toggle = (verstr: string) =>
    setSelected((cur) =>
      cur.includes(verstr)
        ? cur.filter((v) => v !== verstr)
        : [...cur.slice(-1), verstr]
    );

  const openCreate = (open: boolean) =>
    setParams(open ? { new: "1" } : {}, { replace: true });

  const sortLabel = sort ?? primary;

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <Skeleton />;

  return (
    <>
      <PageHead title={appName} what="experiment leaderboard" />
      <p className="page-sub">
        {rows.length} runs
        {sortLabel && (
          <>
            {" · sorted by "}<b>{sortLabel}</b>
            {" · "}{reversed ? "worst first" : "best first"}
          </>
        )}
      </p>

      {creating && (
        <NewExperiment
          ws={ws}
          app={app}
          appName={appName}
          onClose={() => openCreate(false)}
          onCreated={() => {
            const known = new Set(rows.map((r) => r.verstr));
            openCreate(false);
            api.experiments(ws, app, sort ?? undefined).then((next) => {
              setRows(next);
              setFlash(next.find((r) => !known.has(r.verstr))?.verstr ?? null);
            });
          }}
        />
      )}

      {rows.length === 0 ? (
        !creating && (
          <div className="empty">
            No experiments yet. Capture your working state:
            <div className="cli-hint" style={{ margin: "12px auto", maxWidth: 420 }}>
              vmn exp create {appName}
            </div>
            <button className="primary" onClick={() => openCreate(true)}>
              ＋ New experiment
            </button>
          </div>
        )
      ) : (
        <>
          <div className="toolbar">
            <span className="legend-chip">
              <span className="sq" /> best in column
            </span>
            <span className="spacer" />
            {selected.length === 2 && (
              <button
                className="primary"
                onClick={() =>
                  navigate(
                    `/ws/${ws}/app/${app}/compare?v=${encodeURIComponent(selected[0])}&to=${encodeURIComponent(selected[1])}`
                  )
                }
              >
                Compare 2 selected →
              </button>
            )}
            {!creating && (
              <button onClick={() => openCreate(true)}>＋ New experiment</button>
            )}
          </div>

          <ParamPlots rows={rows} metricCols={metricCols} schema={schema} />

          <div className="card flush">
            <div className="tbl-scroll">
              <table style={{ minWidth: 760 }}>
                <thead>
                  <tr>
                    <th style={{ width: 34, paddingLeft: 16 }}></th>
                    <th style={{ width: 40 }}>#</th>
                    <th>experiment</th>
                    {metricCols.map((m) => (
                      <th
                        key={m}
                        className={`sortable${sort === m ? " sorted" : ""}`}
                        onClick={() => clickSort(m)}
                        title={`sort by ${m} (best first)`}
                      >
                        {m}{" "}
                        {colMeta[m].known && (
                          <span className="goal">
                            {colMeta[m].goal === "min" ? "↓" : "↑"}
                          </span>
                        )}
                        {sort === m ? (reversed ? " ▴" : " ▾") : ""}
                      </th>
                    ))}
                    <th>note</th>
                    <th className="num" style={{ paddingRight: 16 }}>when</th>
                  </tr>
                </thead>
                <tbody>
                  {displayed.map((r) => (
                    <tr
                      key={r.verstr}
                      className={[
                        "row",
                        selected.includes(r.verstr) ? "checked" : "",
                        flash === r.verstr ? "flash" : "",
                      ].join(" ")}
                      onClick={() =>
                        navigate(
                          `/ws/${ws}/app/${app}/run/${encodeURIComponent(r.verstr)}`
                        )
                      }
                    >
                      <td
                        style={{ paddingLeft: 16 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={selected.includes(r.verstr)}
                          onChange={() => toggle(r.verstr)}
                        />
                      </td>
                      <td className="idx-cell">@{r.idx}</td>
                      <td>
                        <span className="mono" style={{ color: "var(--accent)" }}>
                          {r.verstr}
                        </span>
                        <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 1 }}>
                          {r.branch}
                        </div>
                      </td>
                      {metricCols.map((m) => {
                        const v = r.metrics[m];
                        const col = colMeta[m];
                        const isBest =
                          typeof v === "number" && v === col.best && rows.length > 1;
                        const isBar = col.isBar && typeof v === "number";
                        let frac = 0;
                        if (isBar) {
                          const span = col.max - col.min;
                          frac = span === 0 ? 1 : (v - col.min) / span;
                          if (col.goal === "min") frac = 1 - frac;
                        }
                        return (
                          <td key={m} className={isBar ? "bar-cell" : ""}>
                            {isBar && (
                              <span
                                className="bar"
                                style={{ width: `${8 + frac * 62}px` }}
                              />
                            )}
                            <span className={`metric${isBest ? " best" : ""}`}>
                              {fmtVal(v)}
                            </span>
                          </td>
                        );
                      })}
                      <td className="note-cell">{r.note}</td>
                      <td className="when-cell" title={r.timestamp ?? ""}>
                        {relTime(r.timestamp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="cli-card">
            vmn exp list {appName}
            {sortLabel ? ` --sort ${sortLabel}` : ""}
          </div>
        </>
      )}
    </>
  );
}
