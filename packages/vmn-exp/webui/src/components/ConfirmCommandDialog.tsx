import { useEffect, useId, useState, type ReactNode } from "react";
import "./ConfirmCommandDialog.css";

/** A modal "run this command?" question for an action with side effects: the
 *  exact CLI command it runs, an optional note on what it touches, Cancel
 *  (focused first, so Enter never runs it) and the confirm button. Escape,
 *  Cancel or a click on the backdrop says no; closing returns focus to the
 *  control that opened it. */
export default function ConfirmCommandDialog({
  title, command, note, confirmLabel = "Run", onConfirm, onCancel,
}: {
  title: string;
  command: string;
  note?: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  useReturnFocus();
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div
        className="card confirm-dialog confirm-command" role="dialog" aria-modal="true" aria-labelledby={titleId}
        onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onCancel(); } }}
      >
        <h2 className="section-title" id={titleId}>{title}</h2>
        <code className="cli-hint">{command}</code>
        {note && <p className="confirm-note">{note}</p>}
        <div className="confirm-actions">
          <button type="button" onClick={onCancel} autoFocus>Cancel</button>
          <button type="button" className="primary" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

/** Read during the first render: by the time effects run, autoFocus has
 *  already moved focus into the dialog. */
function useReturnFocus() {
  const [opener] = useState(() => document.activeElement as HTMLElement | null);
  useEffect(() => () => opener?.focus?.(), [opener]);
}
