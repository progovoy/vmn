/** The job page's header (plan 23 §3.2), a grid: name, `@N` and tree
 *  status left with the actions right on one row (the actions wrap under
 *  on a narrow screen), the full-width progress under them. The tabs follow
 *  as their own sticky row, the CLI twin closes the page. */
import type { ReactNode } from "react";
import type { JobPageSummary } from "../../apiJob";
import { appName as toAppName } from "../../api";
import StatusPill from "../../components/StatusPill";
import Tabs from "../../components/Tabs";
import { sweepQuery } from "../../components/SweepSection";
import { CopyButton } from "../../components/ui";
import { storeUriOf, vmnExpCommand } from "../../shell/cliCommands";
import { usePageScope } from "../../shell/usePageScope";
import JobHeaderProgress from "./JobHeaderProgress";
import { JOB_TAB_LABELS, JOB_TABS, type JobTab } from "./jobQueries";

export const JOB_PANEL_ID = "job-panel";
export const jobTabId = (tab: JobTab) => `job-tab-${tab}`;

/** `vmn-exp list <app> --query 'parent = "<v>"'`: the job's runs on the CLI. */
export const jobListCommand = (appName: string, v: string, storeUri?: string) =>
  vmnExpCommand(["list", appName, "--query", sweepQuery(v)], storeUri);

export function JobCliCard({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const scope = usePageScope(ws);
  const command = jobListCommand(toAppName(app), verstr, storeUriOf(scope.workspace));
  return (
    <div className="cli-card job-cli">
      <code className="mono">{command}</code>
      <CopyButton text={command} className="link" label="Copy the CLI command" />
    </div>
  );
}

export function JobTabs({ tab, onTab }: { tab: JobTab; onTab: (tab: JobTab) => void }) {
  return (
    <Tabs
      tabs={JOB_TABS} tab={tab} onTab={onTab} label="Job" className="board-tabs job-tabs job-tabbar"
      panelId={JOB_PANEL_ID} tabId={jobTabId} render={(t) => JOB_TAB_LABELS[t]}
    />
  );
}

export default function JobHeader({ summary, actions }: { summary: JobPageSummary; actions: ReactNode }) {
  const status = summary.tree_status ?? summary.status;
  return (
    <header className="job-header">
      <div className="job-title">
        <h1 className={summary.name ? undefined : "mono"}>{summary.name || summary.verstr}</h1>
        {summary.name && <span className="mono run-verstr">{summary.verstr}</span>}
        {summary.idx != null && <span className="mono run-idx">@{summary.idx}</span>}
        <StatusPill status={status} />
        {summary.sweep && <span className="badge">sweep</span>}
      </div>
      <div className="job-actions" role="group" aria-label="Job actions">{actions}</div>
      <JobHeaderProgress summary={summary} />
    </header>
  );
}
