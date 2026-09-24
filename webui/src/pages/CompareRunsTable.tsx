import { Link } from "react-router-dom";
import type { ExperimentDetail, MetricsSchema } from "../types";
import { fmtVal, runHref } from "../util";
import StatusPill from "../components/StatusPill";
import { compareRows, runLabel, type CompareRow } from "./compareRunsData";

const MISSING = "—";

function cellText(v: unknown, kind: "params" | "metrics"): string {
  if (v === undefined) return MISSING;
  if (kind === "metrics") return fmtVal(v as number | string | null);
  return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
}

function RunHead({ verstr, detail, base, onRemove }: {
  verstr: string; detail: ExperimentDetail | undefined; base: string; onRemove: (v: string) => void;
}) {
  const st = detail?.status;
  return (
    <th className="compare-run-head">
      <div className="compare-run-title">
        <Link className="mono run-link" to={runHref(base, verstr)}>{runLabel(verstr, detail)}</Link>
        <button
          className="link" aria-label={`remove ${verstr}`} title="remove from comparison"
          onClick={() => onRemove(verstr)}
        >
          ×
        </button>
      </div>
      {st?.status && (
        <StatusPill status={st.status} exitCode={st.exit_code} durationSec={st.duration_sec} staleSec={st.stale_sec} />
      )}
    </th>
  );
}

function Section({ title, kind, rows, width }: {
  title: string; kind: "params" | "metrics"; rows: CompareRow[]; width: number;
}) {
  if (rows.length === 0) return null;
  return (
    <>
      <tr className="compare-section"><th colSpan={width}>{title}</th></tr>
      {rows.map((r) => (
        <tr key={`${kind}:${r.key}`} className={r.differs ? "differs" : ""}>
          <td className="mono compare-key">{r.key}</td>
          {r.values.map((v, i) => (
            <td
              key={i}
              className={`mono${kind === "metrics" ? " metric" : ""}${r.best !== null && v === r.best ? " best" : ""}`}
            >
              {cellText(v, kind)}
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/** Params and metrics of every selected run, one column per run. */
export default function CompareRunsTable({ verstrs, details, schema, base, onlyDiffering, onRemove }: {
  verstrs: string[];
  details: (ExperimentDetail | undefined)[];
  schema: MetricsSchema | null;
  base: string;
  onlyDiffering: boolean;
  onRemove: (verstr: string) => void;
}) {
  const keep = (rows: CompareRow[]) => (onlyDiffering ? rows.filter((r) => r.differs) : rows);
  const params = keep(compareRows(details, "params", schema));
  const metrics = keep(compareRows(details, "metrics", schema));
  const width = verstrs.length + 1;
  return (
    <div className="card flush compare-runs">
      <div className="tbl-scroll" style={{ overflow: "auto" }}>
        <table>
          <thead>
            <tr>
              <th className="compare-key" />
              {verstrs.map((v, i) => (
                <RunHead key={v} verstr={v} detail={details[i]} base={base} onRemove={onRemove} />
              ))}
            </tr>
          </thead>
          <tbody>
            <Section title="metrics" kind="metrics" rows={metrics} width={width} />
            <Section title="params" kind="params" rows={params} width={width} />
            {params.length + metrics.length === 0 && (
              <tr><td colSpan={width} className="empty">
                {onlyDiffering ? "No differences between these runs." : "No params or metrics logged."}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
