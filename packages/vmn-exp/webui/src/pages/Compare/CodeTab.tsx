import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, appName as toAppName } from "../../api";
import type { DiffResult } from "../../types";
import type { HttpError } from "../../http";
import { fmtVal } from "../../util";
import { Skeleton } from "../../components/ui";
import DiffText from "../../components/DiffText";
import RunPicker from "../../components/RunPicker";

/** The metric delta and the real source diff between two runs; on a K6
 *  materialisation failure, the reason, both pickers and the CLI line. */
export default function CodeTab({ ws, app, v, to, onFrom, onTo }: {
  ws: string; app: string; v: string; to: string;
  onFrom: (ref: string) => void; onTo: (ref: string) => void;
}) {
  const appName = toAppName(app);
  const client = useQueryClient();
  // Cached per pair: a revisit paints at once and revalidates behind it.
  const diff = useQuery<DiffResult>({
    queryKey: ["experiments-diff", ws, app, v, to],
    queryFn: () => api.experimentsDiff(ws, app, v, to),
  }, client);
  const result = diff.data ?? null;

  const diffError = diff.error as HttpError | undefined;
  const isMaterializeError = diffError?.status === 422;

  if (diffError && !isMaterializeError)
    return <div className="error">{String(diffError)}</div>;
  if (!result && !diffError) return <Skeleton />;

  const fromVerstr = result?.from_verstr ?? v;
  const toVerstr = result?.to_verstr ?? to;
  const delta = result ? Object.entries(result.metrics_delta) : [];
  const materializeReason = isMaterializeError
    ? ((diffError as HttpError & { body?: { reason?: string } }).body?.reason ?? "restore_failed")
    : null;

  return (
    <>
      <h2 className="section-title">Code diff</h2>
      <p className="page-sub">
        metric delta and the real source diff between two runs
      </p>

      <div className="toolbar" style={{ marginBottom: 18 }}>
        <RunPicker
          ws={ws}
          app={app}
          value={fromVerstr}
          onChange={onFrom}
        />
        <span style={{ color: "var(--text-3)", fontSize: 16 }}>→</span>
        <RunPicker
          ws={ws}
          app={app}
          value={toVerstr}
          onChange={onTo}
        />
      </div>

      {isMaterializeError && (
        <div className="card" style={{ borderLeft: "3px solid var(--bad)" }}>
          <p>
            <strong>Code diff unavailable</strong>: {materializeReason}
          </p>
          <p style={{ color: "var(--text-muted)", marginTop: 4 }}>
            {String(diffError)}
          </p>
          <pre className="cli-card" style={{ marginTop: 8 }}>
            vmn-exp diff {appName} -v {fromVerstr} -v {toVerstr}
          </pre>
        </div>
      )}

      {result && (
        <>
          <div className="card">
            <h2 className="section-title">What happened</h2>
            {delta.length === 0 ? (
              <div className="empty">No metric changes.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>metric</th>
                    <th className="num mono">{fromVerstr}</th>
                    <th className="num mono">{toVerstr}</th>
                    <th className="num">Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {delta.map(([k, d]) => {
                    const numeric =
                      typeof d.from === "number" && typeof d.to === "number";
                    const diff = numeric ? (d.to as number) - (d.from as number) : null;
                    const goal = d.goal ?? null;
                    const neutral = goal === null || d.param;
                    const improved = !neutral && diff !== null && diff !== 0 &&
                      (goal === "min" ? diff < 0 : diff > 0);
                    const color =
                      diff === null || diff === 0 || neutral
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
            <h2 className="section-title">What changed</h2>
            {result.diff.trim()
              ? <DiffText text={result.diff} />
              : <div className="empty">The two runs have identical code.</div>}
          </div>

          <div className="cli-card">
            vmn-exp diff {appName} -v {fromVerstr} -v {toVerstr}
          </div>
        </>
      )}
    </>
  );
}
