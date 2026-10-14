import { useEffect, useRef, useState } from "react";
import RunPicker from "../../components/RunPicker";
import OuterBadge from "../../components/OuterBadge";
import { runHref } from "../../util";
import type { RunChipLabel } from "./useRunLabels";
import "./compare.css";

/** The runs under comparison, shared by every tab: remove one, or add one. */
export default function SelectionChips({ ws, app, labels, onRemove, onAdd }: {
  ws: string; app: string; labels: RunChipLabel[];
  onRemove: (ref: string) => void; onAdd: (ref: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const addButton = useRef<HTMLButtonElement>(null);
  const reopened = useRef(false);
  // Closing the picker hands focus back to the button that opened it.
  useEffect(() => {
    if (adding) reopened.current = true;
    else if (reopened.current) addButton.current?.focus();
  }, [adding]);
  return (
    <div className="compare-chips">
      <ul aria-label="selected runs">
        {labels.map(({ ref, text, missing, outer }) => (
          <li key={ref} className={`compare-chip${missing ? " missing" : ""}`}>
            {missing && "not found: "}
            <span className="mono" title={ref}>{text}</span>
            {outer && <OuterBadge count={outer.count} to={runHref(`/ws/${ws}/app/${app}`, outer.verstr)} />}
            <button className="link" aria-label={`remove ${ref}`} title="remove from the comparison"
              onClick={() => onRemove(ref)}>×</button>
          </li>
        ))}
      </ul>
      {adding ? (
        <RunPicker ws={ws} app={app} value="" label="run to add" autoFocus
          onCancel={() => setAdding(false)} onChange={(v) => { setAdding(false); onAdd(v); }} />
      ) : (
        <button ref={addButton} className="link" onClick={() => setAdding(true)}>+ add run</button>
      )}
    </div>
  );
}
