import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import type { DiffResult, ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal } from "../util";
import { PageHead, Skeleton } from "../components/ui";

function DiffView({ text }: { text: string }) {
  if (!text.trim())
    return <div className="empty">The two experiments have identical code.</div>;
  return (
    <div className="diff">
      <pre>
        {text.split("\n").map((line, i) => {
          let cls = "";
          if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
          else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
          else if (line.startsWith("@@")) cls = "hunk";
          else if (line.startsWith("diff --git")) cls = "file";
          return (
            <div key={i} className={cls}>
              {line || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

function RunSelect({ value, options, onChange }: {
  value: string;
  options: ExperimentRow[];
  onChange: (v: string) => void;
}) {
  const known = options.some((o) => o.verstr === value);
  return (
    <div className="select-wrap" style={{ display: "inline-block" }}>
      <select
        className="mono"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: "auto", fontFamily: "var(--mono)", fontSize: 12.5 }}
      >
        {!known && <option value={value}>{value}</option>}
        {options.map((o) => (
          <option key={o.verstr} value={o.verstr}>
            @{o.idx}  {o.verstr}
          </option>
        ))}
      </select>
    </div>
  );
}

export default function Compare() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const appName = toAppName(app);
  const [params, setParams] = useSearchParams();
  const v = params.get("v") ?? "@1";
  const to = params.get("to") ?? "latest";
  const [result, setResult] = useState<DiffResult | null>(null);
  const [rows, setRows] = useState<ExperimentRow[]>([]);
  const [schema, setSchema] = useState<MetricsSchema | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.experimentsDiff(ws, app, v, to)
      .then(setResult)
      .catch((e) => setError(String(e)));
  }, [ws, app, v, to]);

  useEffect(() => {
    api.experiments(ws, app).then(setRows).catch(() => setRows([]));
    api.metricsSchema(ws, app).then(setSchema).catch(() => setSchema({}));
  }, [ws, app]);

  if (error) return <div className="error">{error}</div>;
  if (!result) return <Skeleton />;

  const delta = Object.entries(result.metrics_delta);

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
        ← experiments
      </Link>
      <PageHead title="Compare runs" mono={false} />
      <p className="page-sub">
        metric delta and the real source diff between two experiments
      </p>

      <div className="toolbar" style={{ marginBottom: 18 }}>
        <RunSelect
          value={result.from_verstr}
          options={rows}
          onChange={(nv) => setParams({ v: nv, to: result.to_verstr })}
        />
        <span style={{ color: "var(--text-3)", fontSize: 16 }}>→</span>
        <RunSelect
          value={result.to_verstr}
          options={rows}
          onChange={(nt) => setParams({ v: result.from_verstr, to: nt })}
        />
      </div>

      <div className="card">
        <div className="eyebrow">what happened</div>
        {delta.length === 0 ? (
          <div className="empty">No metric changes.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>metric</th>
                <th className="num mono">{result.from_verstr}</th>
                <th className="num mono">{result.to_verstr}</th>
                <th className="num">Δ</th>
              </tr>
            </thead>
            <tbody>
              {delta.map(([k, d]) => {
                const numeric =
                  typeof d.from === "number" && typeof d.to === "number";
                const diff = numeric ? (d.to as number) - (d.from as number) : null;
                const goal = metricGoal(schema, k);
                const improved = diff !== null && diff !== 0 &&
                  (goal === "min" ? diff < 0 : diff > 0);
                const color =
                  diff === null || diff === 0
                    ? "var(--text-3)"
                    : improved
                      ? "var(--good)"
                      : "var(--bad)";
                return (
                  <tr key={k}>
                    <td style={{ fontSize: 13 }}>{k}</td>
                    <td className="metric num" style={{ color: "var(--text-2)" }}>
                      {fmtVal(d.from)}
                    </td>
                    <td className="metric num">{fmtVal(d.to)}</td>
                    <td className="metric num" style={{ color, fontWeight: 600 }}>
                      {diff === null ? "–" : (diff > 0 ? "+" : "") + fmtVal(diff)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="eyebrow">what changed</div>
        <DiffView text={result.diff} />
      </div>

      <div className="cli-card">
        vmn exp diff {appName} -v {result.from_verstr} -v {result.to_verstr}
      </div>
    </>
  );
}
