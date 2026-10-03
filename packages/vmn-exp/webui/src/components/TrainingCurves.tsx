import { memo, useMemo, useState, type ReactNode } from "react";
import type { SeriesPoint } from "../types";
import { seriesColor } from "../util";
import { allTimestamped, runOrigin, splitSysMetrics } from "../util/chartData";
import { filterMetrics } from "../util/seriesArrays";
import { xMetricMap, xMetricOptions, type XMap } from "../util/xMetric";
import { useJoinedSeries } from "../hooks/useJoinedSeries";
import { useCurveControls, type CurveControlProps } from "../hooks/useCurveControls";
import { LogToggle, MetricSearch, XMetricSelect, XModeToggle } from "./ChartControls";
import MetricGrid, { type GridView } from "./MetricGrid";
import SmoothingSlider from "./SmoothingSlider";
import MetricKeyPicker from "./MetricKeyPicker";
import type { FetchRange } from "../hooks/useZoomRefetch";
import type { MetricKeysPage, MetricKeysQuery } from "../apiRun";

type Series = Record<string, SeriesPoint[]>;

/** Above this many training metrics, charts are picked from a key list. */
export const MANY_KEYS = 100;
/** Metrics charted at first when they are picked. */
export const SHOWN_BY_DEFAULT = 12;

/** The Run page charts: one small chart per training metric (a loss around
 *  0.1 and an accuracy around 0.9 never share a y axis), plus `sys_*` host
 *  metrics in their own section, hidden until asked for. A metric with a
 *  declared step metric (*stepMetrics*), or every one once an x metric is
 *  picked, is drawn from *fetchJoined*'s series against that metric.
 *  *markStep* (a fork point) is marked on every step chart. *hiddenMetrics*
 *  (`define_metric(hidden=True)` or conf.yml) get a collapsed section too.
 *  Smoothing, x mode, x metric and log scale follow *controls* when given.
 *  *fetchRange* refetches a drag-zoomed step range at full resolution; with
 *  more than MANY_KEYS metrics and *fetchKeys*, the charted ones are picked
 *  from a paged, searchable key list. */
function TrainingCurves({
  series, seriesTotal, startedAt, stepMetrics, fetchJoined, markStep, hiddenMetrics,
  fetchRange, fetchKeys, ...control
}: CurveControlProps & {
  series: Series;
  seriesTotal?: Record<string, number>;
  startedAt?: string | null;
  stepMetrics?: XMap;
  fetchJoined?: (xMap: XMap) => Promise<Series>;
  markStep?: number | null;
  hiddenMetrics?: string[];
  fetchRange?: FetchRange;
  fetchKeys?: (q: MetricKeysQuery) => Promise<MetricKeysPage>;
}) {
  const {
    smoothing: alpha, setSmoothing: setAlpha, xMode, setXMode, x: xChoice, setX: setXChoice, logY, setLogY,
  } = useCurveControls(control);
  const [query, setQuery] = useState("");

  const origin = useMemo(() => runOrigin(series, startedAt), [series, startedAt]);
  const { training, system } = useMemo(
    () => splitSysMetrics(Object.keys(series).filter((m) => series[m].length > 1)),
    [series],
  );
  const hasTimestamps = useMemo(() => allTimestamped(series), [series]);
  const picking = Boolean(fetchKeys) && training.length > MANY_KEYS;
  const [picked, setPicked] = useState<string[] | null>(null);
  const selected = useMemo(() => picked ?? training.slice(0, SHOWN_BY_DEFAULT), [picked, training]);
  const toggle = (name: string) => setPicked(
    selected.includes(name) ? selected.filter((m) => m !== name) : [...selected, name],
  );
  const [shownTraining, shownHidden] = useMemo(() => {
    const hidden = new Set(hiddenMetrics ?? []);
    const chosen = new Set(selected);
    const matching = filterMetrics(picking ? training.filter((m) => chosen.has(m)) : training, query);
    return [matching.filter((m) => !hidden.has(m)), matching.filter((m) => hidden.has(m))];
  }, [training, query, hiddenMetrics, picking, selected]);
  const shownSystem = useMemo(() => filterMetrics(system, query), [system, query]);
  const xOptions = useMemo(() => xMetricOptions(series), [series]);
  const xMap = useMemo(
    () => xMetricMap(training, xMode, xChoice, stepMetrics), [training, xMode, xChoice, stepMetrics],
  );
  const { data: joined, error: joinError } = useJoinedSeries(xMap, fetchJoined, series);
  const view = useMemo<GridView>(
    () => ({ xMode, origin, alpha, logY, markStep }), [xMode, origin, alpha, logY, markStep],
  );
  // Host samples carry no step: always plot them against run time.
  const sysView = useMemo<GridView>(
    () => ({ ...view, xMode: xMode === "wall" ? "wall" : "relative", alpha: 0, markStep: null }),
    [view, xMode],
  );
  const trainColor = useMemo(() => (m: string) => seriesColor(training, m), [training]);
  const sysColor = useMemo(() => (m: string) => seriesColor(system, m), [system]);
  const downsampled = Object.entries(seriesTotal ?? {}).some(
    ([m, n]) => n > (series[m]?.length ?? 0),
  );

  if (training.length === 0 && system.length === 0) return null;

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="eyebrow" style={{ marginBottom: 0 }}>training curves</div>
          <XModeToggle value={xMode} onChange={setXMode} timeEnabled={hasTimestamps} />
          <XMetricSelect value={xChoice} onChange={setXChoice} metrics={xOptions} enabled={xMode === "step"} />
          <LogToggle value={logY} onChange={setLogY} />
          {downsampled && (
            <span style={{ color: "var(--text-3)", fontSize: 11 }} title="the server downsampled long series">
              downsampled
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 12, flexWrap: "wrap" }}>
          <MetricSearch value={query} onChange={setQuery} />
          <SmoothingSlider value={alpha} onChange={setAlpha} />
        </div>
      </div>
      {joinError && <div className="error">{joinError.message}</div>}
      {picking && <MetricKeyPicker fetchPage={fetchKeys!} selected={selected} onToggle={toggle} />}
      {training.length > 0 && shownTraining.length + shownHidden.length === 0 && (
        <div style={{ color: "var(--text-3)", fontSize: 12 }}>No metric matches “{query}”.</div>
      )}
      <MetricGrid
        metrics={shownTraining} series={series} colorOf={trainColor} view={view}
        joined={joined} xMap={xMap} fetchRange={fetchRange}
      />
      <Collapsible label="hidden metrics" count={shownHidden.length}>
        <MetricGrid
          metrics={shownHidden} series={series} colorOf={trainColor} view={view}
          joined={joined} xMap={xMap} fetchRange={fetchRange}
        />
      </Collapsible>
      <Collapsible label="system metrics" count={system.length}>
        <MetricGrid
          metrics={shownSystem} series={series} colorOf={sysColor} view={sysView}
          height={140} minWidth={260}
        />
      </Collapsible>
    </div>
  );
}

/** A "show <label> (count)" link revealing *children*; nothing when count is 0. */
function Collapsible({ label, count, children }: { label: string; count: number; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (count === 0) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <button className="link" onClick={() => setOpen((v) => !v)}>
        {open ? `hide ${label}` : `show ${label} (${count})`}
      </button>
      {open && (
        <div style={{ marginTop: 10 }}>
          <div className="eyebrow">{label}</div>
          {children}
        </div>
      )}
    </div>
  );
}

export default memo(TrainingCurves);
