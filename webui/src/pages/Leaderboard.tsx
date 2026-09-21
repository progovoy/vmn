import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, pollIntervalMs, relTime } from "../util";
import { PageHead, Skeleton } from "../components/ui";
import ParamPlots from "../components/ParamPlots";
import MetricBarChart from "../components/MetricBarChart";
import MetricScatter from "../components/MetricScatter";
import ParallelCoordinates from "../components/ParallelCoordinates";
import GroupedMetrics from "../components/GroupedMetrics";
import NewExperiment from "../components/NewExperiment";
import LeaderboardFilter from "../components/LeaderboardFilter";
import ColumnPicker from "../components/ColumnPicker";
import StatusPill from "../components/StatusPill";
import { usePolling } from "../hooks/usePolling";

export default function Leaderboard() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const appName = toAppName(app);
  const [rows, setRows] = useState<ExperimentRow[] | null>(null);
  const [schema, setSchema] = useState<MetricsSchema | null>(null);
  const [sort, setSort] = useState<string | null>(null);
  const [reversed, setReversed] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [chartView, setChartView] = useState<"trend" | "bar" | "scatter" | "parallel" | "grouped">("trend");
  const [flash, setFlash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [params, setParams] = useSearchParams();
  const creating = params.get("new") === "1";
  const [filteredRows, setFilteredRows] = useState<ExperimentRow[] | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [query, setQuery] = useState("");
  const [queryError, setQueryError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    const args = [ws, app, sort ?? undefined, statusFilter || undefined] as const;
    const request = query
      ? api.experiments(...args, query)
      : api.experiments(...args);
    return request
      .then((next) => {
        setRows(next);
        setQueryError(null);
      })
      .catch((e) => {
        // A 400 is the query the user is still typing: say so beside the box
        // and leave the rows they were reading alone.
        if ((e as { status?: number }).status === 400) setQueryError(String(e.message));
        else setError(String(e));
      });
  }, [ws, app, sort, statusFilter, query]);
  useEffect(() => { load(); }, [load]);
  // Keep refreshing on our own while a run is still in flight, at the cadence
  // its heartbeat can actually move the status at.
  const anyRunning = useMemo(
    () => (rows ?? []).some((r) => r.status === "running"),
    [rows]
  );
  const heartbeatSec = useMemo(() => {
    const beats = (rows ?? [])
      .map((r) => r.heartbeat_interval_sec)
      .filter((v): v is number => typeof v === "number");
    return beats.length ? Math.min(...beats) : null;
  }, [rows]);
  usePolling(load, pollIntervalMs(heartbeatSec), live || anyRunning);
  useEffect(() => {
    api.metricsSchema(ws, app).then(setSchema).catch(() => setSchema({}));
  }, [ws, app]);

  const displayed = useMemo(
    () => (reversed ? [...(filteredRows ?? rows ?? [])].reverse() : filteredRows ?? rows ?? []),
    [filteredRows, rows, reversed]
  );

  const primary = useMemo(
    () => Object.keys(schema ?? {}).find((k) => schema![k].primary) ?? null,
    [schema]
  );
  const metricCols = useMemo(() => {
    const inData = new Set<string>();
    rows?.forEach((r) => Object.keys(r.metrics).forEach((k) => inData.add(k)));
    const fromSchema = Object.keys(schema ?? {}).filter((k) => inData.has(k));
    const extras = [...inData].filter((k) => !(schema ?? {})[k]).sort();
    return [...fromSchema, ...extras];
  }, [rows, schema]);

  const colMeta = useMemo(() => {
    const meta: Record<string, {
      goal: "min" | "max"; best: number | null; isBar: boolean;
      min: number; max: number;
    }> = {};
    metricCols.forEach((m) => {
      const goal = metricGoal(schema, m);
      const vals = (rows ?? [])
        .map((r) => r.metrics[m])
        .filter((v): v is number => typeof v === "number");
      const min = vals.length ? Math.min(...vals) : NaN;
      const max = vals.length ? Math.max(...vals) : NaN;
      meta[m] = {
        goal,
        best: vals.length ? (goal === "min" ? min : max) : null,
        isBar: m === primary && vals.length > 0,
        min, max,
      };
    });
    return meta;
  }, [rows, metricCols, schema, primary]);

  const paramCols = useMemo(() => {
    const keys = new Set<string>();
    rows?.forEach((r) => {
      if (r.user_meta) Object.keys(r.user_meta).forEach((k) => keys.add(k));
    });
    return [...keys].sort();
  }, [rows]);

  const [visibleParams, setVisibleParams] = useState<string[]>([]);
  useEffect(() => { setVisibleParams(paramCols); }, [paramCols]);

  const toggleParam = (col: string) =>
    setVisibleParams((cur) =>
      cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col]
    );

  const clickSort = (m: string) => {
    if (sort === m) setReversed((r) => !r);
    else {
      setSort(m);
      setReversed(false);
    }
  };

  const toggle = (verstr: string) =>
    setSelected((cur) =>
      cur.includes(verstr)
        ? cur.filter((v) => v !== verstr)
        : [...cur, verstr]
    );

  const openCreate = (open: boolean) =>
    setParams(open ? { new: "1" } : {}, { replace: true });

  const sortLabel = sort ?? primary;

  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: displayed.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48,
    overscan: 20,
  });

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <Skeleton />;

  return (
    <>
      <PageHead title={appName} what="experiment leaderboard" />
      <p className="page-sub">
        {filteredRows && filteredRows.length !== rows.length
          ? `${filteredRows.length} of ${rows.length} runs`
          : `${rows.length} runs`}
        {sortLabel && (
          <>
            {" · sorted by "}<b>{sortLabel}</b>
            {" · "}{reversed ? "worst first" : "best first"}
          </>
        )}
      </p>

      {creating && (
        <NewExperiment
          ws={ws}
          app={app}
          appName={appName}
          onClose={() => openCreate(false)}
          onCreated={() => {
            const known = new Set(rows.map((r) => r.verstr));
            openCreate(false);
            api.experiments(ws, app, sort ?? undefined).then((next) => {
              setRows(next);
              setFlash(next.find((r) => !known.has(r.verstr))?.verstr ?? null);
            });
          }}
        />
      )}

      {/* Filtered down to nothing is not "no experiments yet": keep the table
          and its filter bar, or there is no way back from the query. */}
      {rows.length === 0 && !query && !statusFilter ? (
        !creating && (
          <div className="empty">
            No experiments yet. Capture your working state:
            <div className="cli-hint" style={{ margin: "12px auto", maxWidth: 420 }}>
              vmn exp create {appName}
            </div>
            <button className="primary" onClick={() => openCreate(true)}>
              + New experiment
            </button>
          </div>
        )
      ) : (
        <>
          <div className="toolbar">
            <span className="legend-chip">
              <span className="sq" /> best in column
            </span>
            <button
              className={live ? "primary" : ""}
              onClick={() => setLive((v) => !v)}
              style={{ display: "flex", alignItems: "center", gap: 6 }}
            >
              {live && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--good)", animation: "pulse 1.5s infinite" }} />}
              {live ? "Live" : "Live"}
            </button>
            <span className="spacer" />
            {selected.length === 2 && (
              <button
                className="primary"
                onClick={() =>
                  navigate(
                    `/ws/${ws}/app/${app}/compare?v=${encodeURIComponent(selected[0])}&to=${encodeURIComponent(selected[1])}`
                  )
                }
              >
                Compare 2 selected →
              </button>
            )}
            {selected.length >= 2 && (
              <button
                className="primary"
                onClick={() =>
                  navigate(
                    `/ws/${ws}/app/${app}/overlay?runs=${selected.map(encodeURIComponent).join(",")}`
                  )
                }
              >
                Overlay curves →
              </button>
            )}
            {!creating && (
              <button onClick={() => openCreate(true)}>+ New experiment</button>
            )}
            {paramCols.length > 0 && (
              <ColumnPicker columns={paramCols} visible={visibleParams} onToggle={toggleParam} />
            )}
          </div>

          <LeaderboardFilter
            rows={rows}
            onFilter={setFilteredRows}
            onStatusChange={setStatusFilter}
            onQueryChange={setQuery}
            queryError={queryError}
          />

          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <button className={chartView === "trend" ? "primary" : ""} onClick={() => setChartView("trend")}>Trend</button>
            <button className={chartView === "bar" ? "primary" : ""} onClick={() => setChartView("bar")}>Bar</button>
            <button className={chartView === "scatter" ? "primary" : ""} onClick={() => setChartView("scatter")}>Scatter</button>
            <button className={chartView === "parallel" ? "primary" : ""} onClick={() => setChartView("parallel")}>Parallel</button>
            <button className={chartView === "grouped" ? "primary" : ""} onClick={() => setChartView("grouped")}>Grouped</button>
          </div>
          {chartView === "trend" && <ParamPlots rows={displayed} metricCols={metricCols} schema={schema} />}
          {chartView === "bar" && <MetricBarChart rows={displayed} metricCols={metricCols} schema={schema} />}
          {chartView === "scatter" && <MetricScatter rows={displayed} metricCols={metricCols} paramCols={paramCols} schema={schema} />}
          {chartView === "parallel" && <ParallelCoordinates rows={displayed} metricCols={metricCols} paramCols={paramCols} schema={schema} />}
          {chartView === "grouped" && <GroupedMetrics rows={displayed} metricCols={metricCols} paramCols={paramCols} schema={schema} />}

          <div className="card flush">
            <div className="tbl-scroll" ref={parentRef} style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}>
              <table style={{ minWidth: 760 }}>
                <thead>
                  <tr>
                    <th style={{ width: 34, paddingLeft: 16 }}></th>
                    <th style={{ width: 40 }}>#</th>
                    <th style={{ width: 110 }}>status</th>
                    <th>experiment</th>
                    {metricCols.map((m) => (
                      <th
                        key={m}
                        className={`sortable${sort === m ? " sorted" : ""}`}
                        onClick={() => clickSort(m)}
                        title={`sort by ${m} (best first)`}
                      >
                        {m}{" "}
                        {colMeta[m].best !== null && (
                          <span className="goal">
                            {colMeta[m].goal === "min" ? "↓" : "↑"}
                          </span>
                        )}
                        {sort === m ? (reversed ? " ▴" : " ▾") : ""}
                      </th>
                    ))}
                    {visibleParams.map((p) => (
                      <th key={`p-${p}`} style={{ color: "var(--text-3)" }}>{p}</th>
                    ))}
                    <th>note</th>
                    <th className="num" style={{ paddingRight: 16 }}>when</th>
                  </tr>
                </thead>
                <tbody style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
                  {virtualizer.getVirtualItems().map((virtualRow) => {
                    const r = displayed[virtualRow.index];
                    return (
                      <tr
                        key={r.verstr}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          height: virtualRow.size,
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                        className={[
                          "row",
                          selected.includes(r.verstr) ? "checked" : "",
                          flash === r.verstr ? "flash" : "",
                        ].join(" ")}
                        onClick={() =>
                          navigate(
                            `/ws/${ws}/app/${app}/run/${encodeURIComponent(r.verstr)}`
                          )
                        }
                      >
                        <td
                          style={{ paddingLeft: 16 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            checked={selected.includes(r.verstr)}
                            onChange={() => toggle(r.verstr)}
                          />
                        </td>
                        <td className="idx-cell">@{r.idx}</td>
                        <td className="status-cell">
                          {r.status && (
                            <StatusPill
                              status={r.status}
                              exitCode={r.exit_code}
                              durationSec={r.duration_sec}
                              staleSec={r.stale_sec}
                            />
                          )}
                        </td>
                        <td>
                          <div className="nest" style={{ paddingLeft: (r.depth ?? 0) * 14 }}>
                            {(r.depth ?? 0) > 0 && (
                              <span className="nest-mark" title="inner run">⤷</span>
                            )}
                            <span className="mono" style={{ color: "var(--accent)" }}>
                              {r.verstr}
                            </span>
                            {r.children && r.children.length > 0 && (
                              <span className="tree-roll">
                                {r.children.length} inner
                                {r.tree_status && r.tree_status !== r.status
                                  ? ` · tree ${r.tree_status}`
                                  : ""}
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 1 }}>
                            {r.branch}
                          </div>
                        </td>
                        {metricCols.map((m) => {
                          const v = r.metrics[m];
                          const col = colMeta[m];
                          const isBest =
                            typeof v === "number" && v === col.best && rows.length > 1;
                          const isBar = col.isBar && typeof v === "number";
                          let frac = 0;
                          if (isBar) {
                            const span = col.max - col.min;
                            frac = span === 0 ? 1 : (v - col.min) / span;
                            if (col.goal === "min") frac = 1 - frac;
                          }
                          return (
                            <td key={m} className={isBar ? "bar-cell" : ""}>
                              {isBar && (
                                <span
                                  className="bar"
                                  style={{ width: `${8 + frac * 62}px` }}
                                />
                              )}
                              <span className={`metric${isBest ? " best" : ""}`}>
                                {fmtVal(v)}
                              </span>
                            </td>
                          );
                        })}
                        {visibleParams.map((p) => (
                          <td key={`p-${p}`} className="mono" style={{ color: "var(--text-2)", fontSize: 12 }}>
                            {r.user_meta?.[p] != null ? String(r.user_meta[p]) : "—"}
                          </td>
                        ))}
                        <td className="note-cell">{r.note}</td>
                        <td className="when-cell" title={r.timestamp ?? ""}>
                          {relTime(r.timestamp)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="cli-card">
            vmn exp list {appName}
            {sortLabel ? ` --sort ${sortLabel}` : ""}
          </div>
        </>
      )}
    </>
  );
}
