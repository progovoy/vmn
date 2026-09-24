import { useState } from "react";
import { JobCard, useJob } from "./ui";

/** Inline `vmn experiment add -v <verstr> --metrics …` — append more metric
 *  points to this run. Latest value wins in the summary; every point is kept
 *  for the training-curve chart. */
export default function AppendMetrics({ ws, app, appName, verstr, onAdded }: {
  ws: string; app: string; appName: string; verstr: string; onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const { job, error, run } = useJob((j) => {
    if (j.status === "succeeded") {
      setText("");
      setOpen(false);
      onAdded();
    }
  });

  const submit = () => {
    const metrics: Record<string, string> = {};
    for (const pair of text.trim().split(/\s+/).filter(Boolean)) {
      const eq = pair.indexOf("=");
      if (eq < 1) {
        setParseError(`"${pair}" is not key=value`);
        return;
      }
      metrics[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    if (Object.keys(metrics).length === 0) {
      setParseError("enter at least one key=value");
      return;
    }
    setParseError(null);
    run(ws, app, "exp_add", { verstr, metrics });
  };

  if (!open) {
    return (
      <button className="link" style={{ marginTop: 12 }} onClick={() => setOpen(true)}>
        ＋ append metrics
      </button>
    );
  }

  const running = job?.status === "running";
  const cli =
    `vmn exp add ${appName} -v ${verstr}` +
    (text.trim() ? ` --metrics ${text.trim()}` : "");
  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <label className="field">
        add metrics (key=value, space-separated)
        <input
          className="mono"
          placeholder="loss=0.09 acc=0.95"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoFocus
        />
      </label>
      <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
        <button className="primary" onClick={submit} disabled={running}>
          {running ? "Adding…" : "Append"}
        </button>
        <button onClick={() => { setOpen(false); setParseError(null); }}>Cancel</button>
        {(parseError || error) && <span className="error">{parseError || error}</span>}
      </div>
      <div className="cli-hint">{cli}</div>
      {job && job.status === "failed" && <JobCard job={job} />}
    </div>
  );
}
