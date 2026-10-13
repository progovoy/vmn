/** The fleet/sweep table (plan 20 B6): `@N name`, status, the params that
 *  vary among the runs, the goal metric (best marked, D1) and progress when
 *  any run's is known. Every header sorts, with the keyboard too (the
 *  leaderboard's SortButton + `aria-sort`). */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ARIA_SORT, SortButton } from "../pages/LeaderboardHeadParts";
import { fmtParam, fmtVal } from "../util";
import StatusPill from "./StatusPill";
import { bestOf, firstOrder, sortRows, type FleetRow, type Goal, type Order, type SortKey } from "./fleetRows";
import "./fleetTable.css";

const COLLAPSE_THRESHOLD = 10;

interface Column { key: SortKey; label: ReactNode; title: string; num?: boolean }

function columns(paramKeys: string[], metric: { name: string; goal: Goal } | null, trials: boolean, progress: boolean): Column[] {
  const cols: Column[] = [];
  if (trials) cols.push({ key: "trial", label: "trial", title: "sort by trial", num: true });
  cols.push({ key: "label", label: "run", title: "sort by run" }, { key: "status", label: "status", title: "sort by status" });
  for (const p of paramKeys) cols.push({ key: `p:${p}`, label: p, title: `sort by ${p}` });
  if (metric) {
    const arrow = metric.goal && <span className="goal">{metric.goal === "min" ? " ↓" : " ↑"}</span>;
    const how = metric.goal ? "best first" : "high first";
    cols.push({ key: "value", label: <>{metric.name}{arrow}</>, title: `sort by ${metric.name} (${how})`, num: true });
  }
  if (progress) cols.push({ key: "progress", label: "progress", title: "sort by progress" });
  return cols;
}

function Progress({ p }: { p: NonNullable<FleetRow["progress"]> }) {
  return (
    <span className="progress-bar">
      <span>{p.step} / {p.of}</span>
      <span className="progress-track">
        <span className="progress-fill" style={{ width: `${Math.min(100, (p.step / p.of) * 100)}%` }} />
      </span>
    </span>
  );
}

function Value({ row, best, runUrl }: { row: FleetRow; best: boolean; runUrl: (v: string) => string }) {
  const text = <span className={`metric${best ? " best" : ""}`}>{fmtVal(row.value)}</span>;
  if (row.valueFrom && row.value !== null) {
    return <Link to={runUrl(row.valueFrom)} title="from a run nested in this one">{text}</Link>;
  }
  return text;
}

export default function FleetTable({ rows, paramKeys, metric, runUrl, best, rowTestId, label = "Runs" }: {
  rows: FleetRow[];
  paramKeys: string[];
  metric: { name: string; goal: Goal } | null;
  runUrl: (v: string) => string;
  /** The best run's verstr; computed toward the metric's goal when not given. */
  best?: string | null;
  rowTestId?: string;
  label?: string;
}) {
  const [sort, setSort] = useState<{ key: SortKey; order: Order } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const trials = rows.some((r) => r.trial !== undefined);
  const cols = columns(paramKeys, metric, trials, rows.some((r) => r.progress));
  const bestVerstr = best !== undefined ? best : bestOf(rows, metric?.goal ?? null);
  const sorted = sort ? sortRows(rows, sort.key, sort.order) : rows;
  const visible = expanded || sorted.length <= COLLAPSE_THRESHOLD ? sorted : sorted.slice(0, COLLAPSE_THRESHOLD);
  const onSort = (key: SortKey) => setSort((s) => (s?.key === key
    ? { key, order: s.order === "asc" ? "desc" : "asc" }
    : { key, order: firstOrder(key, metric?.goal ?? null) }));

  return (
    <div className="fleet-children fleet-table">
      <table aria-label={label}>
        <thead>
          <tr>
            {cols.map((c) => {
              const on = sort?.key === c.key;
              return (
                <th key={c.key} className={`sortable${on ? " sorted" : ""}${c.num ? " num" : ""}`}
                  aria-sort={on ? ARIA_SORT[sort.order] : "none"} onClick={() => onSort(c.key)}>
                  <SortButton title={c.title} onSort={() => onSort(c.key)}>
                    {c.label}{on ? (sort.order === "asc" ? " ▴" : " ▾") : ""}
                  </SortButton>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => (
            <tr key={r.verstr} data-testid={rowTestId} className={r.verstr === bestVerstr ? "best" : undefined}>
              {trials && <td className="num">{r.trial}</td>}
              <td><Link to={runUrl(r.verstr)} title={r.verstr}>{r.label}</Link></td>
              <td>
                {r.status && <StatusPill status={r.status} />}
                {r.stoppedEarly && <span className="badge">stopped early</span>}
              </td>
              {paramKeys.map((p) => (
                <td key={p} className="mono">{p in r.params ? fmtParam(r.params[p]) : "–"}</td>
              ))}
              {metric && <td className="num"><Value row={r} best={r.verstr === bestVerstr} runUrl={runUrl} /></td>}
              {cols.some((c) => c.key === "progress") && (
                <td>{r.progress ? <Progress p={r.progress} /> : <span style={{ color: "var(--text-3)" }}>{"—"}</span>}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > COLLAPSE_THRESHOLD && !expanded && (
        <button className="link" style={{ marginTop: 8 }} onClick={() => setExpanded(true)}
          aria-label={`Show all ${sorted.length} children`}>
          Show all {sorted.length}
        </button>
      )}
    </div>
  );
}
