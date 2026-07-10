import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { ExperimentRow } from "../types";
import { fmtVal, relTime, shortVerstr } from "../util";

export function AppLayoutNav() {
  const { ws, app } = useParams() as { ws: string; app: string };
  return (
    <nav style={{ display: "flex", gap: 14, marginBottom: 16 }}>
      <NavLink to={`/ws/${ws}/app/${app}`} end>experiments</NavLink>
      <NavLink to={`/ws/${ws}/app/${app}/snapshots`}>snapshots</NavLink>
      <NavLink to={`/ws/${ws}/app/${app}/tree`}>stamp tree</NavLink>
      <NavLink to={`/ws/${ws}/app/${app}/actions`}>actions</NavLink>
    </nav>
  );
}

export default function Leaderboard() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<ExperimentRow[] | null>(null);
  const [sort, setSort] = useState<string | undefined>();
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.experiments(ws, app, sort).then(setRows).catch((e) => setError(String(e)));
  }, [ws, app, sort]);

  const metricCols = useMemo(() => {
    const keys = new Set<string>();
    rows?.forEach((r) => Object.keys(r.metrics).forEach((k) => keys.add(k)));
    return [...keys].sort();
  }, [rows]);

  const toggle = (verstr: string) =>
    setSelected((cur) =>
      cur.includes(verstr)
        ? cur.filter((v) => v !== verstr)
        : [...cur.slice(-1), verstr]
    );

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <div className="empty">Loading…</div>;

  return (
    <>
      <h1>{app.replaceAll("-", "/")}</h1>
      <AppLayoutNav />
      <div className="toolbar">
        <span style={{ color: "var(--text-muted)" }}>
          {rows.length} experiment(s)
        </span>
        {selected.length === 2 && (
          <button
            className="primary"
            onClick={() =>
              navigate(
                `/ws/${ws}/app/${app}/compare?v=${encodeURIComponent(selected[0])}&to=${encodeURIComponent(selected[1])}`
              )
            }
          >
            Compare selected
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <div className="empty">
          No experiments yet. Run one:
          <div className="cli-hint" style={{ marginTop: 10 }}>
            vmn exp run {app.replaceAll("-", "/")} -- python train.py
          </div>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>#</th>
                <th>experiment</th>
                {metricCols.map((m) => (
                  <th
                    key={m}
                    className={sort === m ? "sorted" : ""}
                    onClick={() => setSort(sort === m ? undefined : m)}
                    title={`sort by ${m}`}
                  >
                    {m} {sort === m ? "▾" : ""}
                  </th>
                ))}
                <th>note</th>
                <th>when</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={r.verstr}
                  className="row"
                  onClick={() =>
                    navigate(
                      `/ws/${ws}/app/${app}/run/${encodeURIComponent(r.verstr)}`
                    )
                  }
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.includes(r.verstr)}
                      onChange={() => toggle(r.verstr)}
                    />
                  </td>
                  <td className="mono">@{i + 1}</td>
                  <td className="mono">
                    <Link
                      to={`/ws/${ws}/app/${app}/run/${encodeURIComponent(r.verstr)}`}
                    >
                      {shortVerstr(r.verstr)}
                    </Link>
                  </td>
                  {metricCols.map((m) => (
                    <td key={m} className="metric">
                      {fmtVal(r.metrics[m])}
                    </td>
                  ))}
                  <td className="note">{r.note}</td>
                  <td title={r.timestamp ?? ""}>{relTime(r.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
