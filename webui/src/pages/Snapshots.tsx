import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import type { SnapshotRow } from "../types";
import { relTime } from "../util";
import { PageHead, Skeleton } from "../components/ui";

export default function Snapshots() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<SnapshotRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const appName = toAppName(app);

  useEffect(() => {
    api.snapshots(ws, app).then(setRows).catch((e) => setError(String(e)));
  }, [ws, app]);

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <Skeleton />;

  return (
    <>
      <PageHead title={appName} what="snapshots" />
      <p className="page-sub">
        captured working-tree states — uncommitted changes, local commits,
        untracked files
      </p>
      {rows.length === 0 ? (
        <div className="empty">
          No snapshots. Capture your dirty state:
          <div className="cli-hint" style={{ margin: "12px auto", maxWidth: 480 }}>
            vmn snapshot create {appName} --note "promising results"
          </div>
        </div>
      ) : (
        <>
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
                    <tr key={r.verstr}>
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
