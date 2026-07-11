import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, appName as toAppName, appTag } from "../api";
import type { AppRow, VersionRow } from "../types";
import { JobCard, PageHead, useJob } from "../components/ui";

export default function Actions() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const appName = toAppName(app);
  const [mode, setMode] = useState("patch");
  const [prerelease, setPrerelease] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [apps, setApps] = useState<AppRow[]>([]);
  const [gotoApp, setGotoApp] = useState(appName);
  const [gotoVerstr, setGotoVerstr] = useState("");
  const [gotoVersions, setGotoVersions] = useState<VersionRow[]>([]);
  const { job, error, run } = useJob();

  // A repo can manage many vmn apps — goto targets any of them.
  useEffect(() => {
    api.apps(ws).then(setApps).catch(() => setApps([]));
  }, [ws]);
  useEffect(() => setGotoApp(appName), [appName]);

  useEffect(() => {
    api.versions(ws, appTag(gotoApp))
      .then((rows) => setGotoVersions(rows.filter((r) => r.kind === "version")))
      .catch(() => setGotoVersions([]));
  }, [ws, gotoApp]);

  const stamp = () =>
    run(ws, app, "stamp", {
      release_mode: mode,
      prerelease: prerelease || undefined,
      dry_run: dryRun,
    });

  const gotoRun = () =>
    run(ws, appTag(gotoApp), "goto", { verstr: gotoVerstr.trim() || undefined });

  return (
    <>
      <PageHead title={appName} what="actions" />
      <p className="page-sub">
        run vmn as a real subprocess — takes the repo lock, streams its log
      </p>

      <div className="card-grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-title">Stamp a version</div>
          <div className="form-col">
            <label className="field">
              release mode
              <div className="select-wrap">
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option>patch</option>
                  <option>minor</option>
                  <option>major</option>
                  <option>hotfix</option>
                </select>
              </div>
            </label>
            <label className="field">
              prerelease tag
              <input
                className="mono"
                placeholder="(none)"
                value={prerelease}
                onChange={(e) => setPrerelease(e.target.value)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
              />
              dry run (preview only)
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
          <div className="card-title">Goto a version</div>
          <p className="page-sub" style={{ fontSize: 12.5, marginBottom: 12 }}>
            Restore an app and all its dependency repos to the exact recorded
            state — other apps in this repo are untouched.
          </p>
          <div className="form-col">
            <label className="field">
              app
              <div className="select-wrap">
                <select
                  className="mono"
                  value={gotoApp}
                  onChange={(e) => {
                    setGotoApp(e.target.value);
                    setGotoVerstr("");
                  }}
                >
                  {!apps.some((a) => a.name === gotoApp) && (
                    <option value={gotoApp}>{gotoApp}</option>
                  )}
                  {apps.map((a) => (
                    <option key={a.name} value={a.name}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
            </label>
            <label className="field">
              version
              <input
                className="mono"
                placeholder={
                  gotoVersions.length
                    ? `(none) e.g. ${gotoVersions[gotoVersions.length - 1].verstr}`
                    : "(none) e.g. 1.2.0"
                }
                value={gotoVerstr}
                onChange={(e) => setGotoVerstr(e.target.value)}
                list="goto-versions"
              />
              <datalist id="goto-versions">
                {[...gotoVersions].reverse().map((r) => (
                  <option key={r.verstr} value={r.verstr} />
                ))}
              </datalist>
            </label>
            <button onClick={gotoRun}>Goto</button>
          </div>
          <p className="page-sub" style={{ fontSize: 11.5, marginTop: 8, marginBottom: 0 }}>
            Leave version empty to go to the tip of the current branch.
          </p>
          <div className="cli-hint">
            vmn goto{gotoVerstr.trim() ? ` -v ${gotoVerstr.trim()}` : ""} {gotoApp}
          </div>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {job && <JobCard job={job} />}
    </>
  );
}
