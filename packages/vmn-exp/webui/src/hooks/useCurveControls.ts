import { useCallback, useMemo } from "react";
import type { XMode } from "../util/chartData";
import { AUTO_X } from "../util/xMetric";
import { useControllable } from "./useControllable";

/** The view state a curves chart shares with its toolbar (and a report panel). */
export interface CurveControls {
  smoothing: number;
  xMode: XMode;
  /** The x metric choice: `AUTO_X`, "none" or a metric name. */
  x: string;
  logY: boolean;
}

export interface CurveControlProps {
  /** Controlled fields; any field left out keeps its own state. */
  controls?: Partial<CurveControls>;
  defaultControls?: Partial<CurveControls>;
  onControlsChange?: (next: CurveControls) => void;
}

const DEFAULTS: CurveControls = { smoothing: 0, xMode: "step", x: AUTO_X, logY: false };

type Setters = { [K in keyof CurveControls as `set${Capitalize<K>}`]: (v: CurveControls[K]) => void };

/** Each control is controlled-or-uncontrolled on its own; a change reports
 *  the whole next state. */
export function useCurveControls(
  { controls = {}, defaultControls = {}, onControlsChange }: CurveControlProps,
): CurveControls & Setters {
  const init = { ...DEFAULTS, ...defaultControls };
  const [smoothing, setSmoothing] = useControllable(controls.smoothing, init.smoothing);
  const [xMode, setXMode] = useControllable(controls.xMode, init.xMode);
  const [x, setX] = useControllable(controls.x, init.x);
  const [logY, setLogY] = useControllable(controls.logY, init.logY);
  const current = useMemo(() => ({ smoothing, xMode, x, logY }), [smoothing, xMode, x, logY]);
  const change = useCallback(
    <K extends keyof CurveControls>(key: K, set: (v: CurveControls[K]) => void) =>
      (v: CurveControls[K]) => {
        set(v);
        onControlsChange?.({ ...current, [key]: v });
      },
    [current, onControlsChange],
  );
  return useMemo(() => ({
    ...current,
    setSmoothing: change("smoothing", setSmoothing),
    setXMode: change("xMode", setXMode),
    setX: change("x", setX),
    setLogY: change("logY", setLogY),
  }), [current, change, setSmoothing, setXMode, setX, setLogY]);
}
