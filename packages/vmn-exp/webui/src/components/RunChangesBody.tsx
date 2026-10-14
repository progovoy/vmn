/** What the Changes card shows for one baseline: the run's own patch
 *  (`base`, from /patch) or the diff against another run (experiments-diff),
 *  or one line saying why there is nothing to show. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { fetchRunPatch } from "../apiRunCode";
import type { HttpError } from "../http";
import { diffFiles } from "./diffFiles";
import { DiffToggle, FilesList, MetricDelta } from "./RunChangesParts";
import ParamDeltaBlock from "./ParamDeltaBlock";

const PATCH_REASON: Record<string, string> = {
  no_code: "No code changes captured (clean tree).",
  code_missing: "This run's code object is missing from the store, so its changes can't be shown.",
};

export const DIFF_REASON: Record<string, string> = {
  no_code: "One of the two runs has no captured code to diff.",
  code_missing: "A run's code object is missing from the store, so the diff can't be built.",
  restore_failed: "Restoring the two runs' code to diff them failed.",
};

export const Reason = ({ text }: { text: string }) => <p className="changes-reason">{text}</p>;

export function PatchChanges({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const client = useQueryClient();
  const patch = useQuery({
    queryKey: ["run-patch", ws, app, verstr],
    queryFn: () => fetchRunPatch(ws, app, verstr),
  }, client);
  if (patch.error) return <Reason text={String(patch.error)} />;
  const p = patch.data;
  if (!p) return <Reason text="Loading…" />;
  if (p.text == null) {
    if (p.reason === "untracked_only") {
      const files = p.untracked_files?.length ? `: ${p.untracked_files.join(", ")}` : "";
      return <Reason text={`Only untracked files were captured${files}.`} />;
    }
    return <Reason text={PATCH_REASON[p.reason ?? "no_code"] ?? String(p.reason)} />;
  }
  return (
    <>
      <FilesList files={p.files} />
      <DiffToggle text={p.text} truncated={p.truncated} />
    </>
  );
}

export function RunDiffChanges({ ws, app, from, to }: {
  ws: string; app: string; from: string; to: string;
}) {
  const client = useQueryClient();
  // The Compare code tab's cache key: either page paints the other's result.
  const diff = useQuery({
    queryKey: ["experiments-diff", ws, app, from, to],
    queryFn: () => api.experimentsDiff(ws, app, from, to),
  }, client);
  const error = diff.error as HttpError | null;
  if (error) {
    const reason = (error.body as { reason?: string } | undefined)?.reason;
    return <Reason text={(error.status === 422 && reason && DIFF_REASON[reason]) || String(error)} />;
  }
  const result = diff.data;
  if (!result) return <Reason text="Loading…" />;
  return (
    <>
      <MetricDelta deltas={result.metrics_delta} />
      <ParamDeltaBlock deltas={result.metrics_delta} />
      {result.diff === null
        ? <Reason text={result.diff_unavailable || "No code diff for these runs."} />
        : result.diff.trim()
          ? <FilesList files={diffFiles(result.diff, result.to_verstr)} />
          : <Reason text="The two runs have identical code." />}
      {result.diff !== null && <DiffToggle text={result.diff} />}
    </>
  );
}
