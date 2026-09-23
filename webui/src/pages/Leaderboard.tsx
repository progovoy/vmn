import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import { PAGE_SIZE } from "../paging";
import { isAbortError, withSignal } from "../requestScope";
import { finiteNumbers, maxOf, minOf } from "../util/stats";
import { keepIfUnchanged } from "../util/stableRows";
import { combineQueries, searchClause } from "../util/searchQuery";
import { columnLayout, paramKey } from "./leaderboardColumns";
import { refreshLoaded } from "./leaderboardRefresh";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal, pollIntervalMs, relTime, rowParams } from "../util";
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
  const [total, setTotal] = useState(0);
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
  const [search, setSearch] = useState("");
  const [queryError, setQueryError] = useState<string | null>(null);
  const [brushed, setBrushed] = useState<Set<string> | null>(null);
  const navigate = useNavigate();

  // Every request gets a sequence number: only the newest may land, so a slow
  // response to an old filter can never overwrite the rows of the current one.
  const seqRef = useRef(0);
  const inFlight = useRef<AbortController | null>(null);
  // How many rows the user has paged in — a poll refreshes all of them.
  const loadedRef = useRef(0);

  // The search box searches every run, so it travels with the query.
  const serverQuery = combineQueries(query, searchClause(search));
  // Once a column is picked, the server orders by it — best first by the
  // metric's goal, or worst first — so paging walks the same order.
  const order = useMemo((): "asc" | "desc" | undefined => {
    if (!sort) return undefined;
    const bestAsc = metricGoal(schema, sort) === "min";
    return bestAsc !== reversed ? "asc" : "desc";
  }, [sort, reversed, schema]);

  const load = useCallback((): Promise<ExperimentRow[] | undefined> => {
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;
    const seq = ++seqRef.current;
    const status = statusFilter || undefined;
    const q = serverQuery || undefined;
    const args = [ws, app, sort ?? undefined, status] as const;
    const request = withSignal(ctrl.signal, () =>
      loadedRef.current > PAGE_SIZE || order
        ? refreshLoaded(
            (opts) => api.experimentsPaged(ws, app, opts),
            { sort: sort ?? undefined, status, query: q, order },
            loadedRef.current,
          ).then(({ rows: page, total: n }) => Object.assign(page, { total: n }))
        : q
          ? api.experiments(...args, q)
          : api.experiments(...args)
    );
    return request
      .then((next) => {
        if (seq !== seqRef.current) return undefined;
        loadedRef.current = next.length;
        setRows((prev) => keepIfUnchanged(prev, next));
        setTotal(next.total ?? next.length);
        setQueryError(null);
        return next;
      })
      .catch((e) => {
        if (seq !== seqRef.current || isAbortError(e)) return undefined;
        // A 400 is the query the user is still typing: say so beside the box
        // and leave the rows they were reading alone.
        if ((e as { status?: number }).status === 400) setQueryError(String(e.message));
        else setError(String(e));
        return undefined;
      });
  }, [ws, app, sort, statusFilter, serverQuery, order]);
  useEffect(() => {
    loadedRef.current = 0; // new filters start again from the first page
    load();
  }, [load]);
  useEffect(() => () => inFlight.current?.abort(), []);

  const loadMore = () => {
    if (!rows) return;
    const seq = seqRef.current;
    api.experimentsPaged(ws, app, {
      sort: sort ?? undefined, status: statusFilter || undefined,
      query: serverQuery || undefined, order, offset: rows.length, limit: PAGE_SIZE,
    }).then(({ rows: more, total: n }) => {
      if (seq !== seqRef.current) return; // the filters moved on meanwhile
      setRows((cur) => {
        const known = new Set((cur ?? []).map((r) => r.verstr));
        const merged = [...(cur ?? []), ...more.filter((r) => !known.has(r.verstr))];
        loadedRef.current = merged.length;
        return merged;
      });
      setTotal(n);
    }).catch((e) => { if (!isAbortError(e)) setError(String(e)); });
  };
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
    const fastest = minOf(beats);
    return Number.isNaN(fastest) ? null : fastest;
  }, [rows]);
  usePolling(load, pollIntervalMs(heartbeatSec), live || anyRunning);
  useEffect(() => {
    api.metricsSchema(ws, app).then(setSchema).catch(() => setSchema({}));
  }, [ws, app]);

  // The server already ordered the page, whichever direction was asked for.
  const displayed = useMemo(() => filteredRows ?? rows ?? [], [filteredRows, rows]);

  // A brush in the parallel view narrows the table; the chart keeps every row
  // so its brush indices stay meaningful.
  const onBrush = useCallback(
    (indices: number[] | null) =>
      setBrushed(
        indices
          ? new Set(indices.map((i) => displayed[i]?.verstr).filter((v): v is string => !!v))
          : null
      ),
    [displayed]
  );
  const tableRows = useMemo(
    () =>
      brushed && chartView === "parallel"
        ? displayed.filter((r) => brushed.has(r.verstr))
        : displayed,
    [displayed, brushed, chartView]
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
      const vals = finiteNumbers((rows ?? []).map((r) => r.metrics[m]));
      const min = minOf(vals);
      const max = maxOf(vals);
      meta[m] = {
        goal,
        best: vals.length ? (goal === "min" ? min : max) : null,
        isBar: m === primary && vals.length > 0,
        min, max,
      };
    });
    return meta;
  }, [rows, metricCols, schema, primary]);

  // Keyed on the *set* of names, so a poll returning the same params keeps
  // the same array (and the user's column choices).
  const paramNames = paramKey(rows);
  const paramCols = useMemo(
    () => (paramNames ? paramNames.split("\u0000") : []),
    [paramNames]
  );

  // Hidden columns, not visible ones: a param that appears later shows up,
  // and one the user switched off stays off across polls.
  const [hiddenParams, setHiddenParams] = useState<string[]>([]);
  const visibleParams = useMemo(
    () => paramCols.filter((c) => !hiddenParams.includes(c)),
    [paramCols, hiddenParams]
  );

  const toggleParam = (col: string) =>
    setHiddenParams((cur) =>
      cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col]
    );

  const layout = useMemo(
    () => columnLayout(metricCols.length, visibleParams.length),
    [metricCols.length, visibleParams.length]
  );
  const colWidth = (i: number) => `${layout.widths[i]}px`;
  const metricBase = 4;
  const paramBase = metricBase + metricCols.length;
  const noteIdx = paramBase + visibleParams.length;

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
    count: tableRows.length,
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
        {(() => {
          const shown = tableRows.length;
          const all = Math.max(total, rows.length);
          return shown !== all ? `${shown} of ${all} runs` : `${all} runs`;
        })()}
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
            // The same request as any refresh: the active sort, status and
            // query filters all still apply.
            load().then((next) => {
              if (next) setFlash(next.find((r) => !known.has(r.verstr))?.verstr ?? null);
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
            onSearchChange={setSearch}
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
          {chartView === "parallel" && <ParallelCoordinates rows={displayed} metricCols={metricCols} paramCols={paramCols} schema={schema} onBrush={onBrush} />}
          {chartView === "grouped" && <GroupedMetrics rows={displayed} metricCols={metricCols} paramCols={paramCols} schema={schema} />}

          <div className="card flush">
            <div className="tbl-scroll" ref={parentRef} style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}>
              <table style={{ tableLayout: "fixed", width: layout.total }}>
                <thead>
                  <tr>
                    <th style={{ width: colWidth(0), paddingLeft: 16 }}></th>
                    <th style={{ width: colWidth(1) }}>#</th>
                    <th style={{ width: colWidth(2) }}>status</th>
                    <th style={{ width: colWidth(3) }}>experiment</th>
                    {metricCols.map((m, i) => (
                      <th
                        key={m}
                        style={{ width: colWidth(metricBase + i) }}
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
                    {visibleParams.map((p, i) => (
                      <th key={`p-${p}`} style={{ width: colWidth(paramBase + i), color: "var(--text-3)" }}>{p}</th>
                    ))}
                    <th style={{ width: colWidth(noteIdx) }}>note</th>
                    <th className="num" style={{ width: colWidth(noteIdx + 1), paddingRight: 16 }}>when</th>
                  </tr>
                </thead>
                <tbody style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
                  {virtualizer.getVirtualItems().map((virtualRow) => {
                    const r = tableRows[virtualRow.index];
                    return (
                      <tr
                        key={r.verstr}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: layout.total,
                          height: virtualRow.size,
                          transform: `translateY(${virtualRow.start}px)`,
                          display: "table",
                          tableLayout: "fixed",
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
                          style={{ width: colWidth(0), paddingLeft: 16 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            checked={selected.includes(r.verstr)}
                            onChange={() => toggle(r.verstr)}
                          />
                        </td>
                        <td className="idx-cell" style={{ width: colWidth(1) }}>@{r.idx}</td>
                        <td className="status-cell" style={{ width: colWidth(2) }}>
                          {r.status && (
                            <StatusPill
                              status={r.status}
                              exitCode={r.exit_code}
                              durationSec={r.duration_sec}
                              staleSec={r.stale_sec}
                            />
                          )}
                        </td>
                        <td style={{ width: colWidth(3), overflow: "hidden" }}>
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
                        {metricCols.map((m, i) => {
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
                            <td key={m} className={isBar ? "bar-cell" : ""} style={{ width: colWidth(metricBase + i) }}>
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
                        {visibleParams.map((p, i) => {
                          const pv = rowParams(r)[p];
                          return (
                            <td
                              key={`p-${p}`}
                              className="mono"
                              style={{
                                width: colWidth(paramBase + i), color: "var(--text-2)", fontSize: 12,
                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              }}
                            >
                              {pv != null ? String(pv) : "—"}
                            </td>
                          );
                        })}
                        <td className="note-cell" style={{ width: colWidth(noteIdx), overflow: "hidden" }}>{r.note}</td>
                        <td className="when-cell" style={{ width: colWidth(noteIdx + 1) }} title={r.timestamp ?? ""}>
                          {relTime(r.timestamp)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          {rows.length < total && (
            <div style={{ display: "flex", justifyContent: "center", margin: "10px 0" }}>
              <button onClick={loadMore}>
                Load more ({total - rows.length} remaining)
              </button>
            </div>
          )}
          <div className="cli-card">
            vmn exp list {appName}
            {sortLabel ? ` --sort ${sortLabel}` : ""}
          </div>
        </>
      )}
    </>
  );
}
