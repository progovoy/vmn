import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { SnapshotRow } from "../types";
import { relTime, shortVerstr } from "../util";
import { AppLayoutNav } from "./Leaderboard";

export default function Snapshots() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<SnapshotRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const appName = app.replaceAll("-", "/");

  useEffect(() => {
    api.snapshots(ws, app).then(setRows).catch((e) => setError(String(e)));
  }, [ws, app]);

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <div className="empty">Loading…</div>;

  return (
    <>
      <h1>{appName}</h1>
      <AppLayoutNav />
      {rows.length === 0 ? (
        <div className="empty">
          No snapshots. Capture your dirty state:
          <div className="cli-hint" style={{ marginTop: 10 }}>
            vmn snapshot create {appName} --note "promising results"
          </div>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>snapshot</th>
                <th>base</th>
                <th>branch</th>
                <th>note</th>
                <th>when</th>
                <th>restore</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.verstr}>
                  <td className="mono">@{i + 1}</td>
                  <td className="mono">{shortVerstr(r.verstr)}</td>
                  <td className="mono">{r.base_version}</td>
                  <td className="mono">{r.branch}</td>
                  <td className="note">{r.note}</td>
                  <td title={r.timestamp ?? ""}>{relTime(r.timestamp)}</td>
                  <td>
                    <code>
                      vmn snapshot restore {appName} -v @{i + 1}
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
