import { useQuery } from "@tanstack/react-query";
import { commentTarget } from "../apiReports";
import type { ExperimentDetail, RunStatus } from "../types";
import Comments, { commentsQuery } from "../components/Comments";
import Disclosure from "../components/Disclosure";
import { EnvCard, InputsCard } from "./RunProvenance";
import { MetadataFacts, StatusFacts } from "./RunSections";
import "./runLayout.css";

/** Status details (D5 9): pid, host, heartbeat, command, exit code — and the
 *  run's code metadata — collapsed by default. */
export function StatusDetails({ status, detail, runUrl }: {
  status: RunStatus | null; detail: ExperimentDetail | undefined; runUrl: (v: string) => string;
}) {
  if (!status && !detail) return null;
  return (
    <Disclosure id="run-status-details" title="Status details">
      <div className="run-pair">
        {status && <StatusFacts st={status} runUrl={runUrl} />}
        {detail && <MetadataFacts detail={detail} />}
      </div>
    </Disclosure>
  );
}

/** The run's Python environment and logged inputs, collapsed by default. */
export function RunEnvironment({ detail }: { detail: ExperimentDetail }) {
  const inputs = detail.inputs && Object.keys(detail.inputs).length > 0 ? detail.inputs : null;
  if (!detail.env && !inputs) return null;
  return (
    <Disclosure id="run-environment" title="Environment">
      {detail.env && <EnvCard env={detail.env} nested />}
      {inputs && <InputsCard inputs={inputs} nested />}
    </Disclosure>
  );
}

/** The run's comment thread: open when it has comments, unless the user
 *  closed it. Shares the thread's query, so the count costs no request. */
export function RunComments({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const target = commentTarget.run(app, verstr);
  const { data } = useQuery(commentsQuery(ws, target));
  const any = (data?.comments ?? []).some((c) => !c.deleted);
  return (
    <Disclosure id="run-comments" title="Comments" defaultOpen={any} className="run-comments">
      <Comments ws={ws} target={target} />
    </Disclosure>
  );
}
