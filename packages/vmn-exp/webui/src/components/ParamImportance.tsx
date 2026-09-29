import { memo, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { RowsFilter } from "../queries";
import type { ExperimentRow, MetricsSchema, ParamImportanceEntry } from "../types";
import { fmtVal } from "../util";
import { barPercent, valueMeans } from "../util/importanceData";
import MetricScatter from "./MetricScatter";

interface Props {
  ws: string;
  app: string;
  filter: RowsFilter;
  /** The charted runs: what the scatter / per-value drill-down plots. */
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  /** Target metric to start from (the leaderboard's sort), when it is one. */
  defaultMetric?: string | null;
}

const corrColor = (c: number) => (c > 0 ? "var(--good)" : c < 0 ? "var(--bad)" : undefined);
const fmtCorr = (c: number | null) => (c === null ? "—" : `${c > 0 ? "+" : ""}${c.toFixed(2)}`);

/** Which params drive a metric, as W&B's "parameter importance" panel: a
 *  random-forest importance (bars, scaled to the top param) and the signed
 *  correlation, computed server-side over every run the filter matches.
 *  Clicking a param drills into it against the metric. */
function ParamImportance({ ws, app, filter, rows, metricCols, paramCols, schema, defaultMetric }: Props) {
  const client = useQueryClient();
  // Derived each render: the metric columns can arrive after the first one.
  const [chosen, setMetric] = useState<string | null>(null);
  const metric = [chosen, defaultMetric].find((c) => c && metricCols.includes(c)) ?? metricCols[0] ?? "";
  const [picked, setPicked] = useState<ParamImportanceEntry | null>(null);
  const opts = { status: filter.status, query: filter.query, archived: filter.archived };
  const q = useQuery({
    queryKey: ["experiments-importance", ws, app, metric, opts],
    queryFn: () => api.experimentsImportance(ws, app, metric, opts),
    enabled: Boolean(metric),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: false,
  }, client);
  const entries = q.data ?? [];
  const top = entries[0]?.importance ?? 0;

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 0 }}>parameter importance</div>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          metric
          <select
            aria-label="target metric" value={metric}
            onChange={(e) => { setMetric(e.target.value); setPicked(null); }}
          >
            {metricCols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      {q.isError && <div className="error">{(q.error as Error).message}</div>}
      {q.isSuccess && entries.length === 0 && (
        <div style={{ color: "var(--text-3)", fontSize: 12 }}>No param varies across these runs.</div>
      )}
      {entries.length > 0 && (
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--text-3)", textAlign: "left" }}>
              <th>param</th><th style={{ width: "45%" }}>importance</th><th>correlation</th><th>runs</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr
                key={e.param} onClick={() => setPicked(e)} style={{ cursor: "pointer" }}
                aria-selected={picked?.param === e.param}
              >
                <td className="mono" data-testid="importance-param">{e.param}</td>
                <td title={e.importance.toFixed(3)}>
                  <div style={{ background: "var(--panel-2)", height: 8, borderRadius: 2 }}>
                    <div
                      data-testid="importance-bar"
                      style={{
                        width: `${barPercent(e.importance, top)}%`, height: "100%",
                        background: "var(--accent)", borderRadius: 2,
                      }}
                    />
                  </div>
                </td>
                <td
                  className="mono" data-testid="importance-corr"
                  style={{ color: e.correlation === null ? undefined : corrColor(e.correlation) }}
                  title={e.spearman === null ? undefined : `Spearman ${fmtCorr(e.spearman)}`}
                >
                  {fmtCorr(e.correlation)}
                </td>
                <td className="mono">{e.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {picked && (
        <div style={{ marginTop: 12 }}>
          <Drilldown
            entry={picked} metric={metric} rows={rows} metricCols={metricCols}
            paramCols={paramCols} schema={schema}
          />
        </div>
      )}
    </div>
  );
}

function Drilldown({ entry, metric, rows, metricCols, paramCols, schema }: {
  entry: ParamImportanceEntry; metric: string; rows: ExperimentRow[];
  metricCols: string[]; paramCols: string[]; schema: MetricsSchema | null;
}) {
  if (entry.kind === "numeric") {
    return (
      <MetricScatter
        key={`${entry.param}:${metric}`} rows={rows} metricCols={metricCols}
        paramCols={paramCols}
        schema={schema} initialX={entry.param} initialY={metric}
      />
    );
  }
  return (
    <table style={{ fontSize: 12 }}>
      <thead>
        <tr style={{ color: "var(--text-3)", textAlign: "left" }}>
          <th>{entry.param}</th><th>runs</th><th>mean {metric}</th>
        </tr>
      </thead>
      <tbody>
        {valueMeans(rows, entry.param, metric).map((v) => (
          <tr key={v.value}>
            <td className="mono" data-testid="importance-value">{v.value}</td>
            <td className="mono">{v.n}</td>
            <td className="mono">{fmtVal(v.mean)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default memo(ParamImportance);
