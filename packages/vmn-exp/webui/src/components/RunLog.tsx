import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { runLog } from "../apiRun";
import type { LogEntry } from "../types";
import { fmtVal, relTime } from "../util";

/** Entries fetched per "load older" click. */
export const LOG_PAGE = 500;
/** Up to this many entries render as a plain list; beyond it, virtualized. */
const VIRTUALIZE_ABOVE = 300;
const ROW_H = 26;

const DOT_COLOR: Record<string, string> = {
  create: "var(--accent)",
  run: "var(--good)",
  metrics: "var(--text-3)",
  note: "var(--pre)",
  artifact: "var(--hotfix)",
};

export function describeEntry(e: LogEntry): string {
  switch (e.type) {
    case "create":
      return `created${e.note ? `: ${e.note}` : ""}`;
    case "metrics": {
      const values = (e.values ?? {}) as Record<string, unknown>;
      const step = e.step !== undefined && e.step !== null ? `step ${e.step} — ` : "";
      return `${step}${Object.entries(values)
        .map(([k, v]) => `${k}=${fmtVal(v as number)}`)
        .join(", ")}`;
    }
    case "note":
      return `note: ${e.text}`;
    case "artifact":
      return `artifact: ${e.path} (${e.size} bytes)`;
    case "run":
      return `ran \`${((e.command as string[]) ?? []).join(" ")}\` — exit ${e.exit_code} in ${e.duration_sec}s`;
    default:
      return e.type;
  }
}

function Entry({ e }: { e: LogEntry }) {
  return (
    <>
      <span className="ts">{relTime(e.timestamp)}</span>
      {e._writer && <span className="badge" style={{ fontSize: 10, marginLeft: 6 }}>{e._writer}</span>}
      <span className="what">{describeEntry(e)}</span>
    </>
  );
}

const dotStyle = (e: LogEntry) =>
  ({ "--dot": DOT_COLOR[e.type] ?? "var(--text-3)" }) as React.CSSProperties;

function VirtualList({ entries }: { entries: LogEntry[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({
    count: entries.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 20,
  });
  return (
    <div ref={parentRef} style={{ maxHeight: 480, overflowY: "auto" }}>
      <ul className="timeline" style={{ height: v.getTotalSize(), position: "relative" }}>
        {v.getVirtualItems().map((item) => (
          <li
            key={item.key}
            style={{ ...dotStyle(entries[item.index]), position: "absolute", top: item.start, left: 0, right: 0 }}
          >
            <Entry e={entries[item.index]} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The run log: the server's tail (newest entries) first, older pages on
 *  demand from `/log`. Never holds or renders more than the user asked for. */
export default function RunLog({ ws, app, verstr, tail, total }: {
  ws: string; app: string; verstr: string; tail: LogEntry[]; total: number;
}) {
  // Older entries as one contiguous block at absolute offset `start`. The live
  // tail keeps moving; when it moves past the block, the gap is fetched so the
  // list never silently skips entries.
  const [older, setOlder] = useState<{ start: number; entries: LogEntry[] }>({ start: 0, entries: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A different run starts over.
  useEffect(() => setOlder({ start: 0, entries: [] }), [verstr]);

  const tailStart = Math.max(0, total - tail.length);
  const olderEnd = older.start + older.entries.length;
  const hasOlder = older.entries.length > 0;

  useEffect(() => {
    if (!hasOlder || olderEnd >= tailStart) return;
    runLog(ws, app, verstr, olderEnd, tailStart - olderEnd)
      .then((page) => setOlder((prev) =>
        prev.start + prev.entries.length === olderEnd
          ? { start: prev.start, entries: [...prev.entries, ...page.entries] }
          : prev))
      .catch((e) => setError(String(e)));
  }, [ws, app, verstr, hasOlder, olderEnd, tailStart]);

  const entries = hasOlder
    ? [...older.entries, ...tail.slice(Math.max(0, olderEnd - tailStart))]
    : tail;
  const start = hasOlder ? older.start : tailStart;

  const loadOlder = () => {
    const offset = Math.max(0, start - LOG_PAGE);
    setLoading(true);
    runLog(ws, app, verstr, offset, start - offset)
      .then((page) => setOlder((prev) => ({
        start: offset,
        entries: prev.entries.length
          ? [...page.entries, ...prev.entries]
          : [...page.entries, ...tail],
      })))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  return (
    <div className="card">
      <div className="eyebrow">log</div>
      {start > 0 && (
        <div className="toolbar" style={{ marginBottom: 8 }}>
          <button className="link" onClick={loadOlder} disabled={loading}>
            {loading ? "Loading…" : `load older (${start} more)`}
          </button>
          {error && <span className="error">{error}</span>}
        </div>
      )}
      {entries.length > VIRTUALIZE_ABOVE ? (
        <VirtualList entries={entries} />
      ) : (
        <ul className="timeline">
          {entries.map((e, i) => (
            <li key={start + i} style={dotStyle(e)}>
              <Entry e={e} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
