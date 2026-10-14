/** The job's top-K runs on a metric, their curves overlaid (plan 23 W4).
 *  K <= 10 (or a job with fewer runs) comes from the summary's `top`; more
 *  from the scoped list sorted by the metric. Series via `POST .../series`. */
import { useCallback, useMemo, useState } from "react";
import OverlayChart from "../../components/OverlayChart";
import OverlayLegend from "../../components/OverlayLegend";
import Segmented from "../../components/Segmented";
import { Skeleton } from "../../components/ui";
import { runText } from "../../shell/crumbs";
import { runColor } from "../../util";
import { ChartEmpty, ChartFigure, MetricPicker, type JobChartProps } from "./JobChartParts";
import { TOP_K, useJobTopRuns } from "./jobChartQueries";

/** How many runs the summary's `top` holds at most. */
const SUMMARY_TOP = 10;
const K_OPTIONS = TOP_K.map((k) => [String(k), `Top ${k}`] as const);

function useTopVerstrs({ ws, app, summary, y, state }: JobChartProps) {
  // The summary ranks on its main metric; another metric needs the list.
  const fromSummary = y === (summary.metric ?? y)
    && (state.k <= summary.top.length || summary.top.length < SUMMARY_TOP);
  const query = useJobTopRuns(ws, app, summary.verstr, y, state.k, !fromSummary, summary);
  const verstrs = useMemo(
    () => (fromSummary ? summary.top.slice(0, state.k).map((t) => t.verstr) : query.data ?? null),
    [fromSummary, summary.top, state.k, query.data],
  );
  return { verstrs, error: fromSummary ? null : query.error };
}

export default function JobCurves(p: JobChartProps) {
  const { verstrs, error } = useTopVerstrs(p);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const [focused, setFocused] = useState<string | null>(null);
  const labels = useMemo(() => new Map(p.summary.top.map((t) => [t.verstr, runText(t)])), [p.summary.top]);
  const colorOf = useMemo(() => {
    const idx = new Map((verstrs ?? []).map((v, i) => [v, i]));
    return (v: string) => runColor(idx.get(v) ?? 0);
  }, [verstrs]);
  const toggle = useCallback((v: string) => setHidden((prev) => {
    const next = new Set(prev);
    if (!next.delete(v)) next.add(v);
    return next;
  }), []);

  const body = error ? <div className="error" role="alert">Could not load the top runs: {error.message}</div>
    : !verstrs ? <Skeleton />
    : !verstrs.length ? <ChartEmpty text={`No run of this job has logged ${p.y} yet.`} />
    : (
      <ChartFigure
        label={`${p.y} curves of the job's top ${verstrs.length} runs`}
        caption={`The ${verstrs.length} best runs on ${p.y}, best first. Hover a run to highlight it, click to hide it.`}
      >
        <OverlayLegend runs={verstrs} colorOf={colorOf} labelOf={(v) => labels.get(v) ?? v}
          hidden={hidden} onToggle={toggle} onHover={setFocused} />
        <OverlayChart ws={p.ws} app={p.app} verstrs={verstrs} keys={[p.y]} hidden={hidden} focused={focused} />
      </ChartFigure>
    );
  return (
    <>
      <div className="job-chart-tools">
        <MetricPicker metrics={p.metrics} y={p.y} state={p.state} />
        <Segmented label="Runs to overlay" options={K_OPTIONS} value={String(p.state.k)}
          onChange={(k) => p.state.set({ k })} />
      </div>
      {body}
    </>
  );
}
