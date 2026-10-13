/** An app's experiments page (plan 23 W1): the Jobs view (one row per
 *  top-level run) or All runs (plan 22's board), switched in the board's
 *  head. Switching app starts from a clean slate. */
import { useCallback } from "react";
import { useParams } from "react-router-dom";
import Segmented from "../../components/Segmented";
import { AllRunsView } from "./AllRunsView";
import JobsView from "./JobsView";
import { useExperimentsView, type ExperimentsView } from "./experimentsView";

const VIEW_OPTIONS: readonly (readonly [ExperimentsView, string])[] = [["jobs", "Jobs"], ["all", "All runs"]];

export default function ExperimentsPage() {
  const { ws, app } = useParams() as { ws: string; app: string };
  return <AppExperiments key={`${ws}/${app}`} ws={ws} app={app} />;
}

function AppExperiments({ ws, app }: { ws: string; app: string }) {
  const { view, setView } = useExperimentsView(ws, app);
  const onJobs = useCallback(() => setView("jobs"), [setView]);
  const views = (
    <span className="board-views">
      <Segmented label="Experiments view" options={VIEW_OPTIONS} value={view} onChange={setView} />
    </span>
  );
  return view === "jobs"
    ? <JobsView ws={ws} app={app} views={views} />
    : <AllRunsView ws={ws} app={app} views={views} onJobs={onJobs} />;
}
