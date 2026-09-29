/** `GET .../experiments/{verstr}/sweep`: a sweep's spec, summary and trials,
 *  each trial's metric attributed as `vmn-exp sweep status` does it (the
 *  trial's own, else the run a `start_run()` inside it nested under it). */
import { appTag, get } from "./http";

export interface SweepSpec {
  method: string;
  metric: { name: string; goal: "min" | "max" };
  parameters: Record<string, Record<string, unknown>>;
  run_cap?: number;
  early_terminate?: { type: string; min_iter?: number };
}

export interface SweepTrial {
  verstr: string;
  name: string | null;
  trial: number;
  attempt: number;
  status: string | null;
  params: Record<string, unknown>;
  /** The target metric; null when no run of the trial logged it (yet). */
  value: number | null;
  /** The run the value came from: the trial itself, or a run nested in it. */
  metric_source: string;
  stopped_early: boolean;
}

export interface SweepBest {
  verstr: string;
  name: string | null;
  trial: number;
  value: number;
  params: Record<string, unknown>;
}

export interface SweepView {
  sweep: string;
  spec: SweepSpec;
  summary: {
    counts: Record<string, number>;
    stopped_early: number;
    trials: number;
    best: SweepBest | null;
  };
  trials: SweepTrial[];
}

export function fetchSweep(ws: string, app: string, verstr: string): Promise<SweepView> {
  return get<SweepView>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}/sweep`,
  );
}
