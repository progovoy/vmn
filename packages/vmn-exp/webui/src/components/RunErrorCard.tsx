import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RunError, RunStatus } from "../types";
import { copyText } from "../util";

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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(null), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <button className="run-error-copy" aria-label="copy traceback"
      onClick={() => copyText(text).then((ok) => setCopied(ok ? "copied" : "no clipboard"), () => setCopied("no clipboard"))}>
      {copied ?? "copy"}
    </button>
  );
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
      <CopyButton text={text} />
      <pre ref={ref} className="run-error-traceback">
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
          <pre className="run-error-tail">{tail}</pre>
        </details>
      )}
    </section>
  );
}
