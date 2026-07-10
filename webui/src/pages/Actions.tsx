import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { appTag } from "../api";
import { AppLayoutNav } from "./Leaderboard";

interface Job {
  id: string;
  command: string[];
  status: string;
  exit_code: number | null;
  log: string;
}

function useToken() {
  return sessionStorage.getItem("vmn_token");
}

async function postAction(
  ws: string,
  app: string,
  action: string,
  body: Record<string, unknown>,
  token: string | null
): Promise<Job> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(
    `/api/v1/workspaces/${ws}/apps/${appTag(app)}/actions/${action}`,
    { method: "POST", headers, body: JSON.stringify(body) }
  );
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(b.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export default function Actions() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const appName = app.replaceAll("-", "/");
  const token = useToken();
  const [mode, setMode] = useState("patch");
  const [prerelease, setPrerelease] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number>();

  useEffect(() => () => window.clearInterval(pollRef.current), []);

  const poll = (id: string) => {
    window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(`/api/v1/jobs/${id}`, { headers });
      const j: Job = await res.json();
      setJob(j);
      if (j.status !== "running") window.clearInterval(pollRef.current);
    }, 500);
  };

  const stamp = async () => {
    setError(null);
    try {
      const j = await postAction(ws, app, "stamp", {
        release_mode: mode,
        prerelease: prerelease || undefined,
        dry_run: dryRun,
      }, token);
      setJob(j);
      poll(j.id);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <>
      <h1>{appName}</h1>
      <AppLayoutNav />

      <div className="card">
        <h2 style={{ marginTop: 0 }}>stamp a version</h2>
        <div className="toolbar">
          <label>
            mode{" "}
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option>patch</option>
              <option>minor</option>
              <option>major</option>
              <option>hotfix</option>
            </select>
          </label>
          <label>
            prerelease{" "}
            <input
              placeholder="(none)"
              value={prerelease}
              onChange={(e) => setPrerelease(e.target.value)}
              style={{ width: 90 }}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />{" "}
            dry run
          </label>
          <button className="primary" onClick={stamp}>
            {dryRun ? "Preview" : "Stamp"}
          </button>
        </div>
        <div className="cli-hint">
          vmn stamp -r {mode}
          {prerelease ? ` --pr ${prerelease}` : ""}
          {dryRun ? " --dry-run" : ""} {appName}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {job && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>
            job {job.status}
            {job.exit_code !== null ? ` (exit ${job.exit_code})` : ""}
          </h2>
          <div className="diff">
            <pre>{job.log || "…"}</pre>
          </div>
        </div>
      )}
    </>
  );
}
