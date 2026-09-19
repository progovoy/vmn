import { useState } from "react";
import { JobCard, useJob } from "../components/ui";

/** Inline `vmn exp create` — note + metrics, run as a streamed job. */
export default function NewExperiment({ ws, app, appName, onCreated, onClose }: {
  ws: string; app: string; appName: string;
  onCreated: () => void; onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const [metricsText, setMetricsText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const { job, error, run } = useJob((j) => {
    if (j.status === "succeeded") onCreated();
  });

  const parseMetrics = (): Record<string, string> | null => {
    const out: Record<string, string> = {};
    for (const pair of metricsText.trim().split(/\s+/).filter(Boolean)) {
      const eq = pair.indexOf("=");
      if (eq < 1) {
        setParseError(`"${pair}" is not key=value`);
        return null;
      }
      out[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    setParseError(null);
    return out;
  };

  const submit = () => {
    const metrics = parseMetrics();
    if (metrics === null) return;
    run(ws, app, "exp_create", {
      note: note || undefined,
      metrics: Object.keys(metrics).length ? metrics : undefined,
    });
  };

  const running = job?.status === "running";
  const cli =
    `vmn exp create ${appName}` +
    (note ? ` --note "${note}"` : "") +
    (metricsText.trim() ? ` --metrics ${metricsText.trim()}` : "");

  return (
    <div className="card">
      <div className="eyebrow">new experiment</div>
      <p className="page-sub" style={{ marginBottom: 12 }}>
        Captures the workspace's current working state — dirty files, local
        commits, untracked files — as a reproducible experiment.
      </p>
      <div className="card-grid-2" style={{ marginBottom: 12 }}>
        <label className="field">
          note
          <input
            placeholder="swin-t + mixup 0.2"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            autoFocus
          />
        </label>
        <label className="field">
          metrics (key=value, space-separated)
          <input
            className="mono"
            placeholder="loss=0.12 acc=0.94"
            value={metricsText}
            onChange={(e) => setMetricsText(e.target.value)}
          />
        </label>
      </div>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <button className="primary" onClick={submit} disabled={running}>
          {running ? "Capturing…" : "Create experiment"}
        </button>
        <button onClick={onClose}>Cancel</button>
        {(parseError || error) && <span className="error">{parseError || error}</span>}
      </div>
      <div className="cli-hint">{cli}</div>
      {job && job.status === "failed" && <JobCard job={job} />}
    </div>
  );
}
