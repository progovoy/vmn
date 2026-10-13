import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiReports } from "../apiReports";

/** The Reports page's `New report` dialog: a labelled title field, then the
 *  new report's editor. Escape, Cancel or a click on the backdrop closes it. */
export default function NewReportDialog({ ws, onClose }: { ws: string; onClose: () => void }) {
  const navigate = useNavigate();
  const headingId = useId();
  const titleId = useId();
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { rid } = await apiReports.createReport(ws, { title: title.trim() || "Untitled report", body: "" });
      navigate(`/ws/${ws}/reports/${encodeURIComponent(rid)}/edit`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form
        className="card confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={headingId}
        onSubmit={(e) => void create(e)}
        onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}
        style={{ minWidth: 320 }}
      >
        <h2 className="section-title" id={headingId}>New report</h2>
        <div className="field" style={{ margin: "12px 0" }}>
          <label htmlFor={titleId}>Title</label>
          <input
            id={titleId} value={title} placeholder="Untitled report" autoFocus
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        {error && <div role="alert" className="error">{error}</div>}
        <div className="confirm-actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={busy}>Create</button>
        </div>
      </form>
    </div>
  );
}
