import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, appName as toAppName } from "../api";
import { useMetricsSchema } from "../queries";
import type { DiffResult } from "../types";
import { fmtVal, metricGoal } from "../util";
import { PageHead, Skeleton } from "../components/ui";
import RunPicker from "../components/RunPicker";

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
  const appName = toAppName(app);
  const [params, setParams] = useSearchParams();
  const v = params.get("v") ?? "@1";
  const to = params.get("to") ?? "latest";
  const client = useQueryClient();
  // Cached per pair: a revisit paints at once and revalidates behind it.
  const diff = useQuery<DiffResult>({
    queryKey: ["experiments-diff", ws, app, v, to],
    queryFn: () => api.experimentsDiff(ws, app, v, to),
  }, client);
  const schema = useMetricsSchema(ws, app);
  const result = diff.data ?? null;

  if (diff.error) return <div className="error">{String(diff.error)}</div>;
  if (!result) return <Skeleton />;

  const delta = Object.entries(result.metrics_delta);

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/app/${app}`}>
        ← experiments
      </Link>
      <PageHead title="Code diff" mono={false} />
      <p className="page-sub">
        metric delta and the real source diff between two experiments
      </p>

      <div className="toolbar" style={{ marginBottom: 18 }}>
        <RunPicker
          ws={ws}
          app={app}
          value={result.from_verstr}
          onChange={(nv) => setParams({ v: nv, to: result.to_verstr })}
        />
        <span style={{ color: "var(--text-3)", fontSize: 16 }}>→</span>
        <RunPicker
          ws={ws}
          app={app}
          value={result.to_verstr}
          onChange={(nt) => setParams({ v: result.from_verstr, to: nt })}
        />
        <span className="spacer" />
        <Link
          to={`/ws/${ws}/app/${app}/compare-runs?sel=${encodeURIComponent(result.from_verstr)}` +
            `&sel=${encodeURIComponent(result.to_verstr)}`}
        >
          compare as table →
        </Link>
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
