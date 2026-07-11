import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Job, Workspace } from "../types";
import { copyText } from "../util";

/** Mono app title + muted page label, per the redesign's page header. */
export function PageHead({ title, what, mono = true }: {
  title: string; what?: string; mono?: boolean;
}) {
  return (
    <div className="page-head">
      <h1 className={mono ? "mono" : ""}>{title}</h1>
      {what && <span className="what">{what}</span>}
    </div>
  );
}

/** A workspace's full location — the git checkout path, or its s3 URI. */
export function wsLocation(w: Pick<Workspace, "kind" | "path" | "bucket">): string {
  return w.kind === "s3" ? `s3://${w.bucket}` : w.path ?? "";
}

/** Full path/URI + a copy button — the redesign keeps this visible wherever
 *  a workspace is named, so the location is always one click from the
 *  clipboard (never truncated in the copied value, even if display wraps). */
export function CopyPath({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState<"copied" | "no clipboard" | null>(null);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(null), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);

  return (
    <div className={`copy-path${className ? ` ${className}` : ""}`} title={text}>
      <span className="mono">{text}</span>
      <button
        style={{ padding: "0 8px", fontSize: 11 }}
        onClick={() =>
          copyText(text).then((ok) => setCopied(ok ? "copied" : "no clipboard"))
        }
      >
        {copied ?? "copy"}
      </button>
    </div>
  );
}

export function Skeleton() {
  return (
    <div className="card skeleton" aria-label="loading">
      <div className="line" />
      <div className="line" />
      <div className="line" />
      <div className="line" />
    </div>
  );
}

/** Submit a mutation action and poll its job every 500ms until it settles. */
export function useJob(onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number>();

  useEffect(() => () => window.clearInterval(pollRef.current), []);

  const run = async (
    ws: string, app: string, action: string, body: Record<string, unknown>
  ) => {
    setError(null);
    try {
      const j = await api.action(ws, app, action, body);
      setJob(j);
      window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        const cur = await api.job(j.id);
        setJob(cur);
        if (cur.status !== "running") {
          window.clearInterval(pollRef.current);
          onDone?.(cur);
        }
      }, 500);
    } catch (e) {
      setError(String(e));
    }
  };

  return { job, error, run, clear: () => setJob(null) };
}

export function JobCard({ job }: { job: Job }) {
  const title =
    job.status === "running"
      ? "job running…"
      : `job ${job.status}${job.exit_code !== null ? ` (exit ${job.exit_code})` : ""}`;
  return (
    <div className="card">
      <div className="job-head">
        <span className={`job-dot ${job.status}`} />
        <span className="title">{title}</span>
      </div>
      <div className="diff">
        <pre>{job.log || "…"}</pre>
      </div>
    </div>
  );
}
