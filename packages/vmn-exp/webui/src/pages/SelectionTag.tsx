/** The tray's Tag action: a popover taking `key=value` tags to set and keys
 *  to remove (util/tags.ts parses them as TagEditor does). Enter counts the
 *  runs it changes and asks to confirm; Escape closes it. Problems show in
 *  it; it closes once every tag job succeeded. */
import { type KeyboardEvent, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ConfirmDialog from "../components/ConfirmDialog";
import { useTrayTag } from "../hooks/useTrayTag";
import { plural } from "../util";
import { parseTagEdit, type TagEdit } from "../util/tags";

type TagProps = Omit<Parameters<typeof useTrayTag>[2], "onDone"> & {
  ws: string; app: string;
  /** After the tags are written (the board refreshes). */
  onTagged?: () => void;
};

export default function SelectionTag({ ws, app, onTagged, ...selection }: TagProps) {
  const [open, setOpen] = useState(false);
  const [toSet, setToSet] = useState("");
  const [toRemove, setToRemove] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<{ edit: TagEdit; count: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const close = () => {
    setOpen(false);
    setProblem(null);
    buttonRef.current?.focus();
  };
  const tag = useTrayTag(ws, app, {
    ...selection,
    onDone: () => {
      close();
      setToSet("");
      setToRemove("");
      onTagged?.();
    },
  });

  const ask = () => {
    const parsed = parseTagEdit(toSet, toRemove);
    if ("error" in parsed) {
      setProblem(parsed.error);
      return;
    }
    setProblem(null);
    tag.preview(parsed.edit).then(
      (count) => setConfirming({ edit: parsed.edit, count }),
      (e) => setProblem(`Could not count the runs: ${String((e as Error).message ?? e)}`),
    );
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    } else if (e.key === "Enter" && e.target instanceof HTMLInputElement) {
      e.preventDefault();
      if (!tag.busy) ask();
    }
  };
  const error = problem ?? tag.error;

  return (
    <span className="sel-tag">
      <button
        ref={buttonRef} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? panelId : undefined}
        title="Set or remove tags on the selected runs" onClick={() => (open ? close() : setOpen(true))}
      >
        Tag
      </button>
      {open && (
        <div id={panelId} className="card sel-tag-popover" role="dialog" aria-label="Tag the selected runs" onKeyDown={onKeyDown}>
          <label>
            Tags to set
            <input
              type="text" autoFocus placeholder="key=value, key2=value2" value={toSet}
              onChange={(e) => setToSet(e.target.value)}
            />
          </label>
          <label>
            Tags to remove
            <input type="text" placeholder="key key2" value={toRemove} onChange={(e) => setToRemove(e.target.value)} />
          </label>
          {error && <span className="error" role="alert">{error}</span>}
          <span className="sel-tag-actions">
            <button onClick={close}>Cancel</button>
            <button className="primary" disabled={tag.busy} onClick={ask}>{tag.busy ? "Tagging…" : "Apply"}</button>
          </span>
        </div>
      )}
      {confirming && createPortal(
        <ConfirmDialog
          message={`Tag ${plural(confirming.count, "run")}?`} confirmLabel="Tag"
          onCancel={() => setConfirming(null)}
          onConfirm={() => { tag.apply(confirming.edit); setConfirming(null); }}
        />,
        document.body,
      )}
    </span>
  );
}
