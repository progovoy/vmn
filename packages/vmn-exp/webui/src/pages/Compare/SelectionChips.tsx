import { useState } from "react";
import RunPicker from "../../components/RunPicker";
import { useRunLabels } from "./useRunLabels";
import "./compare.css";

/** The runs under comparison, shared by every tab: remove one, or add one. */
export default function SelectionChips({ ws, app, refs, onRemove, onAdd }: {
  ws: string; app: string; refs: string[];
  onRemove: (ref: string) => void; onAdd: (ref: string) => void;
}) {
  const labels = useRunLabels(ws, app, refs);
  const [adding, setAdding] = useState(false);
  return (
    <div className="compare-chips">
      <ul aria-label="selected runs">
        {labels.map(({ ref, text, missing }) => (
          <li key={ref} className={`compare-chip${missing ? " missing" : ""}`}>
            {missing && "not found: "}
            <span className="mono" title={ref}>{text}</span>
            <button className="link" aria-label={`remove ${ref}`} title="remove from the comparison"
              onClick={() => onRemove(ref)}>×</button>
          </li>
        ))}
      </ul>
      {adding ? (
        <RunPicker ws={ws} app={app} value="" label="run to add" onChange={(v) => { setAdding(false); onAdd(v); }} />
      ) : (
        <button className="link" onClick={() => setAdding(true)}>+ add run</button>
      )}
    </div>
  );
}
