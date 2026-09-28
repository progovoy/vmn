import type { XMode } from "../util/chartData";
import { AUTO_X, NO_X } from "../util/xMetric";

const X_MODES: { mode: XMode; label: string }[] = [
  { mode: "step", label: "Step" },
  { mode: "wall", label: "Wall" },
  { mode: "relative", label: "Relative" },
];

const SMALL_BUTTON = { padding: "2px 8px", fontSize: 11, borderRadius: 4 };

/** Step / wall-clock / time-since-start x axis. Time modes need every point
 *  to carry a timestamp. */
export function XModeToggle({ value, onChange, timeEnabled }: {
  value: XMode;
  onChange: (m: XMode) => void;
  timeEnabled: boolean;
}) {
  return (
    <div style={{ display: "flex", gap: 2, fontSize: 11 }}>
      {X_MODES.map(({ mode, label }) => (
        <button
          key={mode}
          className={value === mode ? "primary" : ""}
          aria-pressed={value === mode}
          style={SMALL_BUTTON}
          disabled={mode !== "step" && !timeEnabled}
          onClick={() => onChange(mode)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** Which metric the step axis is replaced by: each chart's declared step
 *  metric (`auto`), none, or one metric for every chart. */
export function XMetricSelect({ value, onChange, metrics, enabled }: {
  value: string;
  onChange: (v: string) => void;
  metrics: string[];
  enabled: boolean;
}) {
  return (
    <select
      aria-label="x axis metric"
      title="plot against another metric logged at the same step"
      value={value}
      disabled={!enabled}
      onChange={(e) => onChange(e.target.value)}
      style={{ fontSize: 11, padding: "1px 4px" }}
    >
      <option value={AUTO_X}>x: declared</option>
      <option value={NO_X}>x: step</option>
      {metrics.map((m) => <option key={m} value={m}>x: {m}</option>)}
    </select>
  );
}

export function LogToggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      className={value ? "primary" : ""}
      style={SMALL_BUTTON}
      aria-pressed={value}
      title="logarithmic y axis (non-positive values are left out)"
      onClick={() => onChange(!value)}
    >
      Log y
    </button>
  );
}

export function MetricSearch({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="search"
      placeholder="filter metrics"
      aria-label="filter metrics"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ fontSize: 12, padding: "2px 8px", width: 140 }}
    />
  );
}
