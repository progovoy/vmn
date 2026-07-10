import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { Job } from "../types";
import { AppLayoutNav } from "./Leaderboard";

export default function Actions() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const appName = app.replaceAll("-", "/");
  const [mode, setMode] = useState("patch");
  const [prerelease, setPrerelease] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [gotoVerstr, setGotoVerstr] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number>();

  useEffect(() => () => window.clearInterval(pollRef.current), []);

  const poll = (id: string) => {
    window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      const j = await api.job(id);
      setJob(j);
      if (j.status !== "running") window.clearInterval(pollRef.current);
    }, 500);
  };

  const run = async (action: string, body: Record<string, unknown>) => {
    setError(null);
    try {
      const j = await api.action(ws, app, action, body);
      setJob(j);
      poll(j.id);
    } catch (e) {
      setError(String(e));
    }
  };

  const stamp = () =>
    run("stamp", {
      release_mode: mode,
      prerelease: prerelease || undefined,
      dry_run: dryRun,
    });

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

      <div className="card">
        <h2 style={{ marginTop: 0 }}>goto a version of {appName}</h2>
        <p className="subtitle" style={{ marginTop: 0 }}>
          Checks out <span className="mono">{appName}</span> and all its
          dependency repos to the exact state recorded at the given version —
          cloning any missing deps. Other apps in this repo are untouched.
        </p>
        <div className="toolbar">
          <label>
            version{" "}
            <input
              className="mono"
              placeholder="e.g. 1.2.0"
              value={gotoVerstr}
              onChange={(e) => setGotoVerstr(e.target.value)}
              style={{ width: 140 }}
            />
          </label>
          <button
            className="primary"
            disabled={!gotoVerstr.trim()}
            onClick={() => run("goto", { verstr: gotoVerstr.trim() })}
          >
            Goto
          </button>
        </div>
        <div className="cli-hint">
          vmn goto -v {gotoVerstr.trim() || "<version>"} {appName}
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
