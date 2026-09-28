import { memo, useMemo, useState } from "react";
import type { SeriesPoint } from "../types";
import { seriesColor } from "../util";
import { allTimestamped, runOrigin, splitSysMetrics, type XMode } from "../util/chartData";
import { filterMetrics } from "../util/seriesArrays";
import { LogToggle, MetricSearch, XModeToggle } from "./ChartControls";
import MetricGrid, { type GridView } from "./MetricGrid";
import SmoothingSlider from "./SmoothingSlider";

type Series = Record<string, SeriesPoint[]>;

/** The Run page charts: one small chart per training metric (a loss around
 *  0.1 and an accuracy around 0.9 never share a y axis), plus `sys_*` host
 *  metrics in their own section, hidden until asked for. */
function TrainingCurves({ series, seriesTotal, startedAt }: {
  series: Series;
  seriesTotal?: Record<string, number>;
  startedAt?: string | null;
}) {
  const [alpha, setAlpha] = useState(0);
  const [xMode, setXMode] = useState<XMode>("step");
  const [logY, setLogY] = useState(false);
  const [query, setQuery] = useState("");
  const [showSys, setShowSys] = useState(false);

  const origin = useMemo(() => runOrigin(series, startedAt), [series, startedAt]);
  const { training, system } = useMemo(
    () => splitSysMetrics(Object.keys(series).filter((m) => series[m].length > 1)),
    [series],
  );
  const hasTimestamps = useMemo(() => allTimestamped(series), [series]);
  const shownTraining = useMemo(() => filterMetrics(training, query), [training, query]);
  const shownSystem = useMemo(() => filterMetrics(system, query), [system, query]);
  const view = useMemo<GridView>(() => ({ xMode, origin, alpha, logY }), [xMode, origin, alpha, logY]);
  // Host samples carry no step: always plot them against run time.
  const sysView = useMemo<GridView>(
    () => ({ ...view, xMode: xMode === "wall" ? "wall" : "relative", alpha: 0 }), [view, xMode],
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
      {training.length > 0 && shownTraining.length === 0 && (
        <div style={{ color: "var(--text-3)", fontSize: 12 }}>No metric matches “{query}”.</div>
      )}
      <MetricGrid metrics={shownTraining} series={series} colorOf={trainColor} view={view} />
      {system.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button className="link" onClick={() => setShowSys((v) => !v)}>
            {showSys ? "hide system metrics" : `show system metrics (${system.length})`}
          </button>
          {showSys && (
            <div style={{ marginTop: 10 }}>
              <div className="eyebrow">system metrics</div>
              <MetricGrid
                metrics={shownSystem} series={series} colorOf={sysColor} view={sysView}
                height={140} minWidth={260}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(TrainingCurves);
