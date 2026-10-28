/** An app's experiments page (plan 23 W1, §3.1): the Jobs view (one row
 *  per outer run, or per top-level run for an app without them), the Single
 *  runs view (the runs board's columns) or All runs (plan 22's board), switched by one control in the board's head: `Jobs (20) ·
 *  Single runs (19,580) · All runs`, or `Runs · All runs` for an app
 *  without jobs, then the Outer runs view's presets `Live · Review` (plan 28
 *  §4.5). Switching app starts from a clean slate; the views not
 *  shown have their first page prefetched (useViewPrefetch). */
import { useCallback } from "react";
import { useParams } from "react-router-dom";
import Segmented from "../../components/Segmented";
import { useLeaderboardView } from "../../hooks/useLeaderboardView";
import { fmtCount } from "../../util";
import { AllRunsView } from "./AllRunsView";
import JobsView from "./JobsView";
import SinglesView from "./SinglesView";
import { useExperimentsView } from "./experimentsView";
import { useJobsKind, type JobsKind, type JobsKindState } from "./jobsKind";
import { PRESETS, isPreset, type Preset } from "./presets";
import { useViewPrefetch } from "./useViewPrefetch";

type ViewOption = JobsKind | "all";

const PRESET_OPTIONS = (Object.keys(PRESETS) as Preset[]).map((p) => [p, PRESETS[p].label] as const);

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
  const preset = isPreset(view) ? view : undefined;
  useViewPrefetch(ws, app, useLeaderboardView(), view === "all" ? "all" : preset ?? kind.kind ?? "top", kind);
  const onJobs = useCallback(() => setView("jobs"), [setView]);
  const onAll = useCallback(() => setView("all"), [setView]);
  const onPick = useCallback((v: ViewOption) => (v === "all" ? setView("all") : setView("jobs", v)), [setView]);
  const onPreset = useCallback((v: Preset) => setView(v), [setView]);
  // A preset lists outer runs: the Outer runs side, whatever `kind=` says.
  const shownKind = preset && kind.kind ? { ...kind, kind: "jobs" as const, top: "jobs" as const } : kind;
  const views = (
    <span className="board-views">
      <Segmented
        label="Experiments view" options={viewOptions(kind)}
        value={view === "all" ? "all" : shownKind.kind ?? "jobs"} onChange={onPick}
      />
      {kind.kind && (
        <Segmented
          label="Outer runs preset" options={PRESET_OPTIONS}
          value={preset ?? null} onChange={onPreset}
        />
      )}
    </span>
  );
  if (view === "all") return <AllRunsView ws={ws} app={app} views={views} onJobs={onJobs} />;
  return shownKind.kind === "singles"
    ? <SinglesView ws={ws} app={app} views={views} onJobs={onJobs} />
    : <JobsView ws={ws} app={app} views={views} kind={shownKind} preset={preset} onAll={onAll} />;
}
