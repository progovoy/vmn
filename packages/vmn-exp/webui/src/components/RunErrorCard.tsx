import { useLayoutEffect, useRef } from "react";
import type { RunError, RunStatus } from "../types";
import { CopyButton } from "./ui";

/** Anchor of the Run page's output card (RunOutput). */
export const OUTPUT_ANCHOR = "run-output";

function headlineOf(error: RunError | null | undefined, summary: string | null | undefined): string | null {
  if (error?.type && error.message) return `${error.type}: ${error.message}`;
  return error?.message || error?.type || summary || null;
}

function MetaLine({ status, withExit }: { status: RunStatus; withExit: boolean }) {
  const parts: string[] = [];
  if (withExit && status.exit_code != null) parts.push(`exit code ${status.exit_code}`);
  if (status.signal) parts.push(`killed by ${status.signal}`);
  if (!parts.length) return null;
  return <div className="run-error-meta">{parts.join(" · ")}</div>;
}

/** The traceback, scrolled to its end so the raising frame shows first,
 *  with the final `Type: message` line highlighted. */
function Traceback({ text }: { text: string }) {
  const ref = useRef<HTMLPreElement>(null);
  useLayoutEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [text]);
  const lines = text.replace(/\s+$/, "").split("\n");
  const last = lines.pop() ?? "";
  return (
    <div className="run-error-tb-wrap">
      <CopyButton text={text} className="run-error-copy" label="copy traceback" />
      <pre ref={ref} className="yaml-block run-error-traceback">
        {lines.length > 0 && `${lines.join("\n")}\n`}
        <span className="run-error-final">{last}</span>
      </pre>
    </div>
  );
}

function NoException({ exitCode, hasOutputLog }: { exitCode: number | null; hasOutputLog: boolean }) {
  return (
    <div className="run-error-none">
      No exception was recorded{exitCode != null ? ` — exit code ${exitCode}` : ""}.
      {hasOutputLog && <> See the <a href={`#${OUTPUT_ANCHOR}`}>run's output</a> below.</>}
    </div>
  );
}

/** Why a run failed, up front: the exception, its traceback and the last
 *  output. Shown for a failed run, or for any run that recorded an error. */
export default function RunErrorCard({ status, hasOutputLog = false }: {
  status: RunStatus; hasOutputLog?: boolean;
}) {
  const error = status.error;
  if (!error && status.status !== "failed") return null;
  const headline = headlineOf(error, status.error_summary);
  const traceback = error?.traceback;
  const tail = error?.output_tail;
  return (
    <section className="card run-error-card" aria-label="Run error">
      <div className="eyebrow">error</div>
      {headline
        ? <div className="run-error-headline">{headline}</div>
        : <NoException exitCode={status.exit_code} hasOutputLog={hasOutputLog} />}
      <MetaLine status={status} withExit={headline != null} />
      {traceback && <Traceback text={traceback} />}
      {tail && (
        <details className="run-error-output" open={!traceback}>
          <summary>last output</summary>
          <pre className="yaml-block run-error-tail">{tail}</pre>
        </details>
      )}
    </section>
  );
}
