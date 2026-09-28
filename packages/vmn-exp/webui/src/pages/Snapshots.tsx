import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import type { SnapshotRow } from "../types";
import { relTime } from "../util";
import { JobCard, PageHead, Skeleton, useJob } from "../components/ui";

/** Inline `vmn snapshot create` — captures the dirty working tree as a job. */
function NewSnapshot({ ws, app, appName, onCreated, onClose }: {
  ws: string; app: string; appName: string;
  onCreated: () => void; onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const { job, error, run } = useJob((j) => {
    if (j.status === "succeeded" && !j.noop) onCreated();
  });

  const running = job?.status === "running";
  const cli = `vmn snapshot create ${appName}` + (note ? ` --note "${note}"` : "");

  return (
    <div className="card">
      <div className="eyebrow">new snapshot</div>
      <p className="page-sub" style={{ marginBottom: 12 }}>
        Captures the current working tree — uncommitted changes, local
        commits, untracked files — as a restorable snapshot.
      </p>
      <label className="field" style={{ marginBottom: 12 }}>
        note
        <input
          placeholder="promising results"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          autoFocus
        />
      </label>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <button className="primary" onClick={() => run(ws, app, "snapshot_create", { note: note || undefined })} disabled={running}>
          {running ? "Capturing…" : "Create snapshot"}
        </button>
        <button onClick={onClose}>Cancel</button>
        {error && <span className="error">{error}</span>}
        {job && job.status === "succeeded" && job.noop && (
          <span style={{ color: "var(--text-muted)" }}>
            working tree is clean — nothing to snapshot
          </span>
        )}
      </div>
      <div className="cli-hint">{cli}</div>
      {job && job.status === "failed" && <JobCard job={job} />}
    </div>
  );
}

export default function Snapshots() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<SnapshotRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const appName = toAppName(app);

  const load = useCallback(
    () => api.snapshots(ws, app).then(setRows).catch((e) => setError(String(e))),
    [ws, app]
  );
  useEffect(() => { load(); }, [load]);

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <Skeleton />;

  return (
    <>
      <PageHead title={appName} what="snapshots" />
      <p className="page-sub">
        captured working-tree states — uncommitted changes, local commits,
        untracked files
      </p>

      {creating && (
        <NewSnapshot
          ws={ws}
          app={app}
          appName={appName}
          onClose={() => setCreating(false)}
          onCreated={() => {
            const known = new Set(rows.map((r) => r.verstr));
            setCreating(false);
            api.snapshots(ws, app).then((next) => {
              setRows(next);
              setFlash(next.find((r) => !known.has(r.verstr))?.verstr ?? null);
            });
          }}
        />
      )}

      {rows.length === 0 ? (
        !creating && (
          <div className="empty">
            No snapshots. Capture your dirty state:
            <div className="cli-hint" style={{ margin: "12px auto", maxWidth: 480 }}>
              vmn snapshot create {appName} --note "promising results"
            </div>
            <button className="primary" onClick={() => setCreating(true)}>
              ＋ New snapshot
            </button>
          </div>
        )
      ) : (
        <>
          {!creating && (
            <div className="toolbar">
              <span className="spacer" />
              <button onClick={() => setCreating(true)}>＋ New snapshot</button>
            </div>
          )}
          <div className="card flush">
            <div className="tbl-scroll">
              <table style={{ minWidth: 680 }}>
                <thead>
                  <tr>
                    <th style={{ width: 44, paddingLeft: 16 }}>#</th>
                    <th>snapshot</th>
                    <th>base</th>
                    <th>branch</th>
                    <th>note</th>
                    <th className="num" style={{ paddingRight: 16 }}>when</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.verstr} className={flash === r.verstr ? "flash" : ""}>
                      <td className="idx-cell" style={{ paddingLeft: 16 }}>@{i + 1}</td>
                      <td className="mono" style={{ color: "var(--accent)" }}>
                        {r.verstr}
                      </td>
                      <td className="mono" style={{ color: "var(--text-2)" }}>
                        {r.base_version}
                      </td>
                      <td className="mono" style={{ color: "var(--text-2)" }}>
                        {r.branch}
                      </td>
                      <td className="note-cell">{r.note}</td>
                      <td className="when-cell" title={r.timestamp ?? ""}>
                        {relTime(r.timestamp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="cli-card">
            vmn snapshot restore {appName} -v @N
          </div>
        </>
      )}
    </>
  );
}
