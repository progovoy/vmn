import type { XMode } from "../util/chartData";
import { AUTO_X, NO_X } from "../util/xMetric";
import "./XAxisControl.css";

const TIME_MODES: readonly (readonly [XMode, string])[] = [["wall", "Wall"], ["relative", "Relative"]];

/** The metric picked as the x axis, or "" when the axis is step or time. */
const pickedMetric = (xMode: XMode, x: string) =>
  (xMode === "step" && x !== AUTO_X && x !== NO_X ? x : "");

/** One labelled x-axis choice: step (each metric's declared step metric,
 *  else the step), wall clock, time since start, or one metric for every
 *  chart. Time needs every point to carry a timestamp. */
export default function XAxisControl({ xMode, x, metrics, timeEnabled, onXMode, onX }: {
  xMode: XMode;
  x: string;
  metrics: string[];
  timeEnabled: boolean;
  onXMode: (m: XMode) => void;
  onX: (x: string) => void;
}) {
  const metric = pickedMetric(xMode, x);
  const stepOn = xMode === "step" && !metric;
  const pickStep = () => { onXMode("step"); onX(AUTO_X); };
  const pickTime = (m: XMode) => { onXMode(m); onX(AUTO_X); };
  const pickMetric = (m: string) => {
    if (!m) return pickStep();
    onXMode("step");
    onX(m);
  };
  return (
    <div className="segmented x-axis-control" role="group" aria-label="x axis">
      <span className="x-axis-label" aria-hidden>x axis</span>
      <button type="button" className={stepOn ? "primary" : ""} aria-pressed={stepOn} onClick={pickStep}
        title="step, or each metric's declared step metric">
        Step
      </button>
      {TIME_MODES.map(([m, text]) => (
        <button key={m} type="button" className={xMode === m ? "primary" : ""} aria-pressed={xMode === m}
          disabled={!timeEnabled} onClick={() => pickTime(m)}>
          {text}
        </button>
      ))}
      <span className={`select-wrap${metric ? " on" : ""}`}>
        <select aria-label="x axis metric" title="plot against another metric logged at the same step"
          value={metric} onChange={(e) => pickMetric(e.target.value)}>
          <option value="">x = metric…</option>
          {metrics.map((m) => <option key={m} value={m}>x = {m}</option>)}
        </select>
      </span>
    </div>
  );
}
