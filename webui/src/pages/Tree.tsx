import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { VersionRow } from "../types";
import { AppLayoutNav } from "./Leaderboard";

export default function Tree() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<VersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const appName = app.replaceAll("-", "/");

  useEffect(() => {
    api.versions(ws, app).then(setRows).catch((e) => setError(String(e)));
  }, [ws, app]);

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <div className="empty">Loading…</div>;

  const versions = rows.filter((r) => r.kind === "version").reverse();
  const roots = rows.filter((r) => r.kind === "root").reverse();

  return (
    <>
      <h1>{appName}</h1>
      <AppLayoutNav />
      {versions.length === 0 && roots.length === 0 ? (
        <div className="empty">No stamped versions yet.</div>
      ) : (
        <>
          {versions.length > 0 && (
            <div className="card">
              <h2 style={{ marginTop: 0 }}>versions (newest first)</h2>
              <table>
                <thead>
                  <tr>
                    <th>version</th>
                    <th>mode</th>
                    <th>branch</th>
                    <th>commit</th>
                    <th>from</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr key={v.tag}>
                      <td className="mono">{v.verstr}</td>
                      <td>
                        <span className={`badge mode-${v.release_mode}`}>
                          {v.release_mode}
                        </span>
                      </td>
                      <td className="mono">{v.branch}</td>
                      <td className="mono">{v.commit?.slice(0, 7)}</td>
                      <td className="mono">{v.previous_version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {roots.length > 0 && (
            <div className="card">
              <h2 style={{ marginTop: 0 }}>root versions</h2>
              <table>
                <thead>
                  <tr>
                    <th>root</th>
                    <th>services</th>
                  </tr>
                </thead>
                <tbody>
                  {roots.map((v) => (
                    <tr key={v.tag}>
                      <td className="mono">{v.verstr}</td>
                      <td className="mono">
                        {Object.entries(v.services ?? {})
                          .map(([s, ver]) => `${s}@${ver}`)
                          .join("  ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
