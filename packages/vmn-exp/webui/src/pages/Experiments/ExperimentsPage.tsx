/** An app's experiments page (plan 23 W1, §3.1): the Jobs view (one row
 *  per top-level run, the jobs or the single runs) or All runs (plan 22's
 *  board), switched by one control in the board's head: `Jobs (20) ·
 *  Single runs (19,580) · All runs`, or `Runs · All runs` for an app
 *  without jobs. Switching app starts from a clean slate. */
import { useCallback } from "react";
import { useParams } from "react-router-dom";
import Segmented from "../../components/Segmented";
import { fmtCount } from "../../util";
import { AllRunsView } from "./AllRunsView";
import JobsView from "./JobsView";
import SinglesView from "./SinglesView";
import { useExperimentsView } from "./experimentsView";
import { useJobsKind, type JobsKind, type JobsKindState } from "./jobsKind";
import { useViewPrefetch } from "./useViewPrefetch";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";

type ViewOption = JobsKind | "all";

const counted = (text: string, n: number | undefined) => (n === undefined ? text : `${text} (${fmtCount(n)})`);

function viewOptions(kind: JobsKindState): [ViewOption, string][] {
  if (!kind.kind) return [["jobs", "Runs"], ["all", "All runs"]];
  return [
    ["jobs", counted("Outer runs", kind.counts?.jobs)],
    ["singles", counted("Single runs", kind.counts?.singles)],
    ["all", "All runs"],
  ];
}

export default function ExperimentsPage() {
  const { ws, app } = useParams() as { ws: string; app: string };
  return <AppExperiments key={`${ws}/${app}`} ws={ws} app={app} />;
}

function AppExperiments({ ws, app }: { ws: string; app: string }) {
  const { view, setView } = useExperimentsView(ws, app);
  const kind = useJobsKind(ws, app);
  useViewPrefetch(ws, app, useLeaderboardView(), view === "all" ? "all" : kind.kind ?? "top", kind);
  const onJobs = useCallback(() => setView("jobs"), [setView]);
  const onAll = useCallback(() => setView("all"), [setView]);
  const onPick = useCallback((v: ViewOption) => (v === "all" ? setView("all") : setView("jobs", v)), [setView]);
  const views = (
    <span className="board-views">
      <Segmented
        label="Experiments view" options={viewOptions(kind)}
        value={view === "all" ? "all" : kind.kind ?? "jobs"} onChange={onPick}
      />
    </span>
  );
  if (view === "all") return <AllRunsView ws={ws} app={app} views={views} onJobs={onJobs} />;
  return kind.kind === "singles"
    ? <SinglesView ws={ws} app={app} views={views} onJobs={onJobs} />
    : <JobsView ws={ws} app={app} views={views} kind={kind} onAll={onAll} />;
}
