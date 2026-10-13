/** `vmn goto` of a run through the Actions job runner (plan 20 D8): the
 *  command is shown and runs only on an explicit confirm. */
import { useId } from "react";
import { JobCard, useJob } from "./ui";

export default function RunGotoDialog({ ws, app, verstr, command, onClose }: {
  ws: string; app: string; verstr: string; command: string; onClose: () => void;
}) {
  const titleId = useId();
  const { job, error, run } = useJob();
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className="card confirm-dialog run-goto-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}
        onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}
      >
        <p id={titleId}>Check out this run's code here?</p>
        <p className="run-goto-why">
          Moves this checkout and its deps to the run's state. Dirty work is saved as a snapshot first.
        </p>
        <div className="cli-hint">{command}</div>
        {error && <div className="error" role="alert">{error}</div>}
        {job && <JobCard job={job} />}
        <div className="confirm-actions">
          {job ? (
            <button type="button" onClick={onClose} autoFocus>Close</button>
          ) : (
            <>
              <button type="button" onClick={onClose}>Cancel</button>
              <button type="button" className="primary" autoFocus
                onClick={() => void run(ws, app, "goto", { verstr })}>
                Run goto
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
