/** "Add to report": append the current view as a panel to an existing or new report. */
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiReports } from "../apiReports";
import type { PanelSpec } from "./panelSpec";
import { appendPanel, createReportWithPanel } from "./appendPanel";

type Done = { rid: string; title: string };

function Picker({ ws, spec, onClose }: { ws: string; spec: PanelSpec; onClose: () => void }) {
  const reports = useQuery({ queryKey: ["reports", ws, false], queryFn: () => apiReports.listReports(ws) });
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Done | null>(null);

  const run = async (work: () => Promise<Done>) => {
    setBusy(true);
    setError(null);
    try {
      setDone(await work());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const addTo = (rid: string, name: string) => run(async () => (await appendPanel(ws, rid, spec), { rid, title: name }));
  const create = (e: FormEvent) => {
    e.preventDefault();
    if (title.trim()) void run(async () => ({ rid: await createReportWithPanel(ws, title.trim(), spec), title: title.trim() }));
  };

  return (
    <div className="modal-backdrop">
      <div role="dialog" aria-label="Add to report" className="card modal">
        {done ? (
          <p>Added to <Link to={`/ws/${ws}/reports/${encodeURIComponent(done.rid)}`}>{done.title}</Link></p>
        ) : (
          <>
            {reports.error && <div role="alert" className="error">{(reports.error as Error).message}</div>}
            <ul style={{ listStyle: "none", padding: 0 }}>
              {(reports.data?.reports ?? []).map((r) => (
                <li key={r.rid}>
                  <button type="button" className="link" disabled={busy}
                    onClick={() => void addTo(r.rid, r.title || r.rid)}>{r.title || r.rid}</button>
                </li>
              ))}
            </ul>
            <form onSubmit={create} style={{ display: "flex", gap: 8 }}>
              <input aria-label="New report title" placeholder="new report" value={title}
                onChange={(e) => setTitle(e.target.value)} />
              <button type="submit" className="btn" disabled={busy}>Create</button>
            </form>
          </>
        )}
        {error && <div role="alert" className="error">{error}</div>}
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

/** `spec` is called when opening, so the panel captures the view at that moment. */
export default function AddToReport({ ws, spec }: { ws: string; spec: () => PanelSpec | null }) {
  const [open, setOpen] = useState<PanelSpec | null>(null);
  if (!spec()) return null;
  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(spec())}>Add to report</button>
      {open && <Picker ws={ws} spec={open} onClose={() => setOpen(null)} />}
    </>
  );
}
