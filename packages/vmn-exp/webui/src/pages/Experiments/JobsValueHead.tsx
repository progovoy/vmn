/** The Outer runs value column's header (plan 31 §2): the answered
 *  aggregate (`median · dates`) and the menu picking `job_agg*`, each
 *  choice checked as the URL has it, else as the rows answered it (the
 *  app's default); nothing is checked before either says. */
import JobAggMenu from "../../components/JobAggMenu";
import type { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { rolledHeader } from "../../util/jobAggregate";
import type { ColumnHead } from "./JobsTable";
import type { useJobsBoard } from "./useJobsBoard";

type View = ReturnType<typeof useLeaderboardView>;
type Board = ReturnType<typeof useJobsBoard>;

/** Children, every run, and a unit per param or tag key of the app: every
 *  param, not only Group by's few-valued ones (a date has hundreds). */
function byOptions(facets: Board["facets"]): string[] {
  const params = (facets?.param_keys ?? []).map((k) => `field:params.${k}`);
  const tags = (facets?.tag_keys ?? []).map((k) => `field:tags.${k}`);
  return ["children", "runs", ...params, ...tags];
}

export function jobsValueHead(view: View, board: Board): ColumnHead {
  const { rolled, facets } = board;
  const { jobAgg, setJobAgg, resetJobAgg } = view;
  const shown = {
    agg: jobAgg.agg ?? rolled?.agg ?? null,
    by: jobAgg.by ?? rolled?.by ?? null,
    value: jobAgg.value ?? rolled?.source ?? null,
    metric: jobAgg.metric ?? rolled?.metric ?? null,
    nested: jobAgg.nested ?? rolled?.nested,
  };
  return {
    label: rolled ? rolledHeader(rolled) : null,
    menu: (
      <JobAggMenu
        shown={shown} goal={rolled?.goal ?? null} byOptions={byOptions(facets)} metricOptions={facets?.metric_keys ?? []}
        onPick={setJobAgg} onReset={resetJobAgg}
      />
    ),
  };
}
