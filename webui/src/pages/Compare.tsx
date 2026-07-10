import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { DiffResult } from "../types";
import { fmtVal, shortVerstr } from "../util";
import { AppLayoutNav } from "./Leaderboard";

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

export default function Compare() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [params] = useSearchParams();
  const v = params.get("v") ?? "@1";
  const to = params.get("to") ?? "latest";
  const [result, setResult] = useState<DiffResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.experimentsDiff(ws, app, v, to)
      .then(setResult)
      .catch((e) => setError(String(e)));
  }, [ws, app, v, to]);

  if (error) return <div className="error">{error}</div>;
  if (!result) return <div className="empty">Loading…</div>;

  const delta = Object.entries(result.metrics_delta);
  return (
    <>
      <h1>
        Compare{" "}
        <span className="mono">
          {shortVerstr(result.from_verstr)} → {shortVerstr(result.to_verstr)}
        </span>
      </h1>
      <AppLayoutNav />

      <div className="card">
        <h2 style={{ marginTop: 0 }}>what happened</h2>
        {delta.length === 0 ? (
          <div className="empty">No metric changes.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>metric</th>
                <th>{shortVerstr(result.from_verstr)}</th>
                <th>{shortVerstr(result.to_verstr)}</th>
                <th>Δ</th>
              </tr>
            </thead>
            <tbody>
              {delta.map(([k, d]) => {
                const numeric =
                  typeof d.from === "number" && typeof d.to === "number";
                const diff = numeric ? (d.to as number) - (d.from as number) : null;
                return (
                  <tr key={k}>
                    <td>{k}</td>
                    <td className="metric">{fmtVal(d.from)}</td>
                    <td className="metric">{fmtVal(d.to)}</td>
                    <td className="metric">
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
        <h2 style={{ marginTop: 0 }}>what changed</h2>
        <DiffView text={result.diff} />
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>cli equivalent</h2>
        <div className="cli-hint">
          vmn exp diff {app.replaceAll("-", "/")} -v {result.from_verstr} -v {result.to_verstr}
        </div>
      </div>
    </>
  );
}
