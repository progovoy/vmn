/** An outer run's Runs tab (plan 28 N6): its runs flat (the scoped board,
 *  JobRuns) or as a tree under the same filters (JobTreeRuns), switched by
 *  `layout=flat|tree`; without it the app's last choice (localStorage),
 *  else DEFAULT_LAYOUT. */
import { useEffect } from "react";
import Segmented from "../../components/Segmented";
import { useUrlState } from "../../hooks/useUrlState";
import { useScopedStatus } from "../../shell/useShellData";
import { rememberChoice, storedChoice } from "../../util/appChoice";
import JobRuns from "./JobRuns";
import JobTreeRuns from "./JobTreeRuns";

type RunsLayout = "flat" | "tree";

/** The layout before a reader picks one. */
export const DEFAULT_LAYOUT: RunsLayout = "tree";
const LAYOUT_KEY = "vmn_job_runs_layout";

const LAYOUTS: readonly (readonly [RunsLayout, string])[] = [["flat", "Flat"], ["tree", "Tree"]];
const isLayout = (v: string | null): v is RunsLayout => v === "flat" || v === "tree";

type Props = Parameters<typeof JobRuns>[0];

export default function JobRunsTab(props: Props) {
  const { ws, app, verstr, name } = props;
  const { params, update } = useUrlState();
  const raw = params.get("layout");
  const layout = (isLayout(raw) ? raw : null) ?? storedChoice(LAYOUT_KEY, ws, app, isLayout) ?? DEFAULT_LAYOUT;
  useEffect(() => { rememberChoice(LAYOUT_KEY, ws, app, layout); }, [ws, app, layout]);
  const attention = useScopedStatus(ws, app, verstr).data?.attention;

  return (
    <div className="job-runs-tab">
      <div className="job-runs-layout">
        <Segmented label="Layout" options={LAYOUTS} value={layout}
          onChange={(next) => update((p) => { p.set("layout", next); })} />
      </div>
      {layout === "tree"
        ? <JobTreeRuns ws={ws} app={app} verstr={verstr} name={name} attention={attention} />
        : <JobRuns {...props} />}
    </div>
  );
}
