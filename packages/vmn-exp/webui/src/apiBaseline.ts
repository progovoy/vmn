/** An outer run against its baseline (plan 28 N3): `experiments/{v}/baseline`
 *  (the card) and `experiments-baselines?v=` (many outer runs' chips at once,
 *  a Jobs view page's). Index-backed: no per-run store reads. */
import { appTag, get } from "./http";
import type { RunState } from "./types";

/** A value here and on the baseline, their change and whether it is an
 *  improvement (null: no direction, a value missing, or no change). */
export interface BaselineDelta {
  value: number | null;
  baseline: number | null;
  delta: number | null;
  better: boolean | null;
}

/** How the baseline was picked: `?to=`, a `baseline=true` tag, or the latest ended alike. */
export type BaselineSource = "to" | "pinned" | "latest";

export interface BaselineRef {
  verstr: string;
  idx: number | null;
  name: string | null;
  status: RunState | null;
  source: BaselineSource;
  started_at: string | null;
  finished_at: string | null;
}

export type ChipState = "worse" | "better" | "same" | "pending";

/** `▼ best_value from 2024-12 (5 of 41 trade_date values worse than the
 *  baseline's p10)`: `worse` of the `of` finished pairs past the baseline's
 *  worst decile (`quantile`), the first of them `from`. Without paired
 *  children, the best value's change (`worse`/`of` null). */
export interface BaselineChipData {
  state: ChipState;
  text: string;
  metric: string;
  from: string | null;
  worse: number | null;
  of: number | null;
  quantile: "p10" | "p90" | null;
  threshold: number | null;
}

/** A chip with the run it compares against (the chips endpoint's). */
export interface BaselineChipEntry extends BaselineChipData {
  baseline: BaselineRef;
}

/** One pair of direct children sharing a value of `by`, in key order. */
export interface BaselinePair extends BaselineDelta {
  key: string;
  label: string;
  verstr: string;
  idx: number | null;
  baseline_verstr: string;
  done: boolean;
  worse?: boolean;
}

export interface BaselineAttention extends BaselineDelta {
  key: string;
  label: string;
  level: "warn" | "error";
  q: string;
  count: number | null;
  baseline_count: number | null;
  error?: string;
}

export interface BaselineCompare {
  verstr: string;
  match: string[];
  by: string | null;
  values: Record<string, unknown>;
  baseline: BaselineRef | null;
  metric: string | null;
  goal: "min" | "max" | null;
  metrics: Record<string, { best: BaselineDelta; median: BaselineDelta }>;
  failed_pct: BaselineDelta | null;
  duration_p90: BaselineDelta | null;
  attention: BaselineAttention[];
  own: Record<string, BaselineDelta>;
  pairs: BaselinePair[];
  pairs_total: number;
  chip: BaselineChipData | null;
}

const base = (ws: string, app: string) => `/workspaces/${ws}/apps/${appTag(app)}`;

export function jobBaseline(ws: string, app: string, v: string): Promise<BaselineCompare> {
  return get<BaselineCompare>(`${base(ws, app)}/experiments/${encodeURIComponent(v)}/baseline`);
}

export const MAX_CHIPS = 200;

/** The chips of *verstrs* (null: no baseline), in requests of at most `MAX_CHIPS`. */
export async function baselineChips(ws: string, app: string, verstrs: readonly string[]):
  Promise<Record<string, BaselineChipEntry | null>> {
  const parts: string[][] = [];
  for (let i = 0; i < verstrs.length; i += MAX_CHIPS) parts.push(verstrs.slice(i, i + MAX_CHIPS));
  const answers = await Promise.all(parts.map((part) => {
    const p = new URLSearchParams(part.map((v) => ["v", v]));
    return get<{ chips: Record<string, BaselineChipEntry | null> }>(`${base(ws, app)}/experiments-baselines?${p}`);
  }));
  return Object.assign({}, ...answers.map((a) => a.chips));
}
