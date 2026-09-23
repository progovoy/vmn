import { useMemo, useState } from "react";
import type { SeriesPoint } from "../types";
import { seriesColor } from "../util";
import {
  allTimestamped, buildRows, capSeries, runOrigin, splitSysMetrics, type XMode,
} from "../util/chartData";
import CurveChart from "./CurveChart";
import SmoothingSlider from "./SmoothingSlider";

type Series = Record<string, SeriesPoint[]>;

function Legend({ keys }: { keys: string[] }) {
  return (
    <>
      {keys.map((m) => (
        <span key={m} style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-2)" }}>
          <span style={{ width: 14, height: 3, borderRadius: 2, background: seriesColor(keys, m) }} />
          {m}
        </span>
      ))}
    </>
  );
}

/** The Run page charts: training metrics on one chart, `sys_*` host metrics on
 *  their own (hidden until asked for) so an RSS in the thousands never
 *  flattens a loss around 0.1. Each metric keeps all of its own points. */
export default function TrainingCurves({ series, seriesTotal, startedAt }: {
  series: Series;
  seriesTotal?: Record<string, number>;
  startedAt?: string | null;
}) {
  const [alpha, setAlpha] = useState(0);
  const [xMode, setXMode] = useState<XMode>("step");
  const [showSys, setShowSys] = useState(false);

  const capped = useMemo(() => capSeries(series), [series]);
  const origin = useMemo(() => runOrigin(capped, startedAt), [capped, startedAt]);
  const { training, system } = useMemo(
    () => splitSysMetrics(Object.keys(capped).filter((m) => capped[m].length > 1)),
    [capped],
  );
  const hasTimestamps = useMemo(() => allTimestamped(capped), [capped]);
  const trainRows = useMemo(
    () => buildRows(capped, training, xMode, origin), [capped, training, xMode, origin],
  );
  // Host samples carry no step: always plot them against run time.
  const sysMode: XMode = xMode === "wall" ? "wall" : "relative";
  // One small chart per host metric: CPU % and RSS MB don't share a scale.
  const sysRows = useMemo(
    () => (showSys ? system.map((m) => buildRows(capped, [m], sysMode, origin)) : []),
    [showSys, capped, system, sysMode, origin],
  );
  const downsampled = Object.entries(seriesTotal ?? {}).some(
    ([m, n]) => n > (series[m]?.length ?? 0),
  );

  if (training.length === 0 && system.length === 0) return null;
  const colorOf = (keys: string[]) => (k: string) => seriesColor(keys, k);

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="eyebrow" style={{ marginBottom: 0 }}>training curves</div>
          <div style={{ display: "flex", gap: 2, fontSize: 11 }}>
            {(["step", "wall", "relative"] as const).map((mode) => (
              <button
                key={mode}
                className={xMode === mode ? "primary" : ""}
                style={{ padding: "2px 8px", fontSize: 11, borderRadius: 4 }}
                disabled={mode !== "step" && !hasTimestamps}
                onClick={() => setXMode(mode)}
              >
                {mode === "step" ? "Step" : mode === "wall" ? "Wall" : "Relative"}
              </button>
            ))}
          </div>
          {downsampled && (
            <span style={{ color: "var(--text-3)", fontSize: 11 }} title="the server downsampled long series">
              downsampled
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 12, flexWrap: "wrap" }}>
          <Legend keys={training} />
          <SmoothingSlider value={alpha} onChange={setAlpha} />
        </div>
      </div>
      {training.length > 0 && (
        <CurveChart rows={trainRows} keys={training} colorOf={colorOf(training)} alpha={alpha} xMode={xMode} />
      )}
      {system.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button className="link" onClick={() => setShowSys((v) => !v)}>
            {showSys ? "hide system metrics" : `show system metrics (${system.length})`}
          </button>
          {showSys && (
            <div style={{ marginTop: 10 }}>
              <div className="eyebrow">system metrics</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
                {system.map((m, i) => (
                  <div key={m}>
                    <div className="mono" style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 4 }}>{m}</div>
                    <CurveChart rows={sysRows[i] ?? []} keys={[m]} colorOf={colorOf(system)} alpha={0} xMode={sysMode} height={140} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
