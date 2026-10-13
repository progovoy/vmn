import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, appName as toAppName } from "../../api";
import type { DiffResult } from "../../types";
import type { HttpError } from "../../http";
import { fmtVal } from "../../util";
import { Skeleton } from "../../components/ui";
import DiffText from "../../components/DiffText";
import RunPicker from "../../components/RunPicker";
import CopyRefButton from "../../components/CopyRefButton";
import ParamDeltaBlock from "../../components/ParamDeltaBlock";
import { deltaTone, fmtDelta, numericChange, type DeltaTone } from "../../components/diffDeltaTone";
import { useRunLabels } from "./useRunLabels";

const TONE_COLOR: Record<DeltaTone, string> = {
  better: "var(--good)", worse: "var(--bad)", flat: "var(--text-3)",
};

/** A delta column's head: the side's `@N name`, verstr in the title (D3). */
function SideHead({ verstr, label }: { verstr: string; label: string }) {
  return (
    <th className="num compare-ident">
      <span className="mono" title={verstr}>{label}</span>
      <CopyRefButton text={verstr} />
    </th>
  );
}

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
  const fromVerstr = result?.from_verstr ?? v;
  const toVerstr = result?.to_verstr ?? to;
  const [fromLabel, toLabel] = useRunLabels(ws, app, [fromVerstr, toVerstr]);

  const diffError = diff.error as HttpError | undefined;
  const isMaterializeError = diffError?.status === 422;

  if (diffError && !isMaterializeError)
    return <div className="error">{String(diffError)}</div>;
  if (!result && !diffError) return <Skeleton />;

  const delta = result ? Object.entries(result.metrics_delta).filter(([, d]) => !d.param) : [];
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
              <table aria-label="Metric changes">
                <thead>
                  <tr>
                    <th>metric</th>
                    <SideHead verstr={fromVerstr} label={fromLabel.text} />
                    <SideHead verstr={toVerstr} label={toLabel.text} />
                    <th className="num">Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {delta.map(([k, d]) => {
                    const diff = numericChange(d);
                    const color = TONE_COLOR[deltaTone(d, diff)];
                    return (
                      <tr key={k}>
                        <td style={{ fontSize: 13 }}>{k}</td>
                        <td className="metric num" style={{ color: "var(--text-2)" }}>
                          {fmtVal(d.from)}
                        </td>
                        <td className="metric num">{fmtVal(d.to)}</td>
                        <td className="metric num" style={{ color, fontWeight: 600 }}>
                          {fmtDelta(diff)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            <ParamDeltaBlock
              deltas={result.metrics_delta}
              heads={[
                <SideHead key="from" verstr={fromVerstr} label={fromLabel.text} />,
                <SideHead key="to" verstr={toVerstr} label={toLabel.text} />,
              ]}
            />
          </div>

          <div className="card">
            <h2 className="section-title">What changed</h2>
            {result.diff === null
              ? <div className="empty">{result.diff_unavailable || "No code diff for these runs."}</div>
              : result.diff.trim()
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
