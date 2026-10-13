import { Link } from "react-router-dom";
import type { ExperimentDetail, MetricsSchema } from "../types";
import { fmtVal, runHref } from "../util";
import CopyRefButton from "../components/CopyRefButton";
import StatusPill from "../components/StatusPill";
import { compareRows, runLabel, type CompareRow } from "./compareRunsData";

const MISSING = "—";

function cellText(v: unknown, kind: "params" | "metrics"): string {
  if (v === undefined) return MISSING;
  if (kind === "metrics") return fmtVal(v as number | string | null);
  return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
}

function RunHead({ verstr, detail, base }: {
  verstr: string; detail: ExperimentDetail | undefined; base: string;
}) {
  const st = detail?.status;
  return (
    <th className="compare-run-head compare-ident">
      <div className="compare-run-title">
        <Link className="mono run-link" to={runHref(base, verstr)} title={verstr}>{runLabel(verstr, detail)}</Link>
        <CopyRefButton text={verstr} />
      </div>
      {st?.status && (
        <StatusPill status={st.status} exitCode={st.exit_code} durationSec={st.duration_sec} staleSec={st.stale_sec} />
      )}
    </th>
  );
}

function Section({ title, kind, rows, width, note }: {
  title: string; kind: "params" | "metrics"; rows: CompareRow[]; width: number; note?: string;
}) {
  if (rows.length === 0) return null;
  return (
    <>
      <tr className="compare-section">
        <th colSpan={width} scope="row">
          <span className="label-caps">{title}</span>
          {note && <span className="compare-section-note"> · {note}</span>}
        </th>
      </tr>
      {rows.map((r) => (
        <tr key={`${kind}:${r.key}`} data-section={kind} className={r.differs ? "differs" : ""}>
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
export default function CompareRunsTable({ verstrs, details, schema, base, onlyDiffering }: {
  verstrs: string[];
  details: (ExperimentDetail | undefined)[];
  schema: MetricsSchema | null;
  base: string;
  onlyDiffering: boolean;
}) {
  const keep = (rows: CompareRow[]) => (onlyDiffering ? rows.filter((r) => r.differs) : rows);
  const allParams = compareRows(details, "params", schema);
  const changed = allParams.filter((r) => r.differs).length;
  const params = keep(allParams);
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
                <RunHead key={v} verstr={v} detail={details[i]} base={base} />
              ))}
            </tr>
          </thead>
          <tbody>
            <Section title="metrics" kind="metrics" rows={metrics} width={width} />
            <Section title="params" kind="params" rows={params} width={width}
              note={`${changed} of ${allParams.length} changed`} />
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
