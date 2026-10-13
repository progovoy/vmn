/** The pieces every job chart shares (plan 23 W4): what a chart knows about
 *  the job, its pickers, a named figure with its caption, and the columns'
 *  loading / error / empty states. */
import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { JobSummary } from "../../apiJob";
import { Skeleton } from "../../components/ui";
import type { ExperimentColumns } from "../../types";
import { plural } from "../../util";
import type { JobChartState } from "./jobChartQueries";

/** The job as a chart sees it, its axes already resolved to existing keys. */
export interface JobChartProps {
  ws: string;
  app: string;
  summary: JobSummary;
  metrics: string[];
  params: string[];
  /** Params taking more than one value. */
  varying: string[];
  /** Params with 2..20 values: what a colour or a box chart can group by. */
  groupable: string[];
  y: string;
  state: JobChartState;
}

/** A param's or metric's column key. */
export const colKey = (name: string, params: readonly string[]) =>
  params.includes(name) ? `params.${name}` : `metrics.${name}`;

export function Picker({ label, value, options, onChange, names }: {
  label: string; value: string; options: readonly string[]; onChange: (v: string) => void;
  names?: (v: string) => string;
}) {
  return (
    <label className="job-picker">
      {label}
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o} value={o}>{names ? names(o) : o}</option>)}
      </select>
    </label>
  );
}

export const MetricPicker = ({ metrics, y, state }: Pick<JobChartProps, "metrics" | "y" | "state">) => (
  <Picker label="Metric" value={y} options={metrics} onChange={(v) => state.set({ y: v })} />
);

export const ColorPicker = ({ value, groupable, state }: { value: string; groupable: string[]; state: JobChartState }) => (
  <Picker label="Colour by" value={value} options={["status", ...groupable]} onChange={(v) => state.set({ color: v })} />
);

/** The resolved colour-by: status, else a groupable param. */
export const colorChoice = (state: JobChartState, groupable: string[]) =>
  state.color && groupable.includes(state.color) ? state.color : "status";

/** A chart as one named figure, its caption saying what it shows. */
export function ChartFigure({ label, caption, children }: { label: string; caption: ReactNode; children: ReactNode }) {
  return (
    <figure className="job-chart" aria-label={label}>
      {children}
      <figcaption className="job-chart-caption">{caption}</figcaption>
    </figure>
  );
}

/** `N runs`, noting when the job holds more than the columns carried. */
export function runsCaption(n: number, data: ExperimentColumns): string {
  const more = data.total > data.verstrs.length ? ` (the first ${plural(data.verstrs.length, "run")} of ${data.total.toLocaleString("en-US")})` : "";
  return `${plural(n, "run")}${more}`;
}

/** The columns' loading and error states; *children* once they are in. */
export function ColumnsState({ query, children }: {
  query: UseQueryResult<ExperimentColumns>; children: (data: ExperimentColumns) => ReactNode;
}) {
  if (query.isError) {
    return <div className="error" role="alert">Could not load the job&apos;s runs: {query.error.message}</div>;
  }
  return query.data ? <>{children(query.data)}</> : <Skeleton />;
}

export const ChartEmpty = ({ text }: { text: string }) => <p className="muted job-empty">{text}</p>;
