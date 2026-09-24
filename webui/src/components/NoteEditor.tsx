import { useRef, useState } from "react";
import { useAppQueryClient } from "../queryClient";
import { runKey, type RowsData } from "../queries";
import type { ExperimentDetail } from "../types";
import { useJob } from "./ui";

/** The run's note, editable in place (`vmn exp add -v <verstr> --note …`).
 *  The new note shows the moment Save is pressed; the caches take it once the
 *  job succeeds, and a failed job puts the old note back. */
export default function NoteEditor({ ws, app, verstr, note }: {
  ws: string; app: string; verstr: string; note: string | null;
}) {
  const client = useAppQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  // The job's completion callback outlives the render that started it.
  const pendingRef = useRef<string | null>(null);

  const commit = (saved: string) => {
    client.setQueryData<ExperimentDetail>(runKey(ws, app, verstr), (d) =>
      d && { ...d, metadata: { ...d.metadata, note: saved } });
    client.setQueriesData<RowsData>({ queryKey: ["experiments", ws, app] }, (data) =>
      data && { ...data, rows: data.rows.map((r) => (r.verstr === verstr ? { ...r, note: saved } : r)) });
  };
  const { error, run } = useJob((j) => {
    if (j.status === "succeeded" && pendingRef.current !== null) commit(pendingRef.current);
    setFailed(j.status !== "succeeded");
    pendingRef.current = null;
    setPending(null);
  });

  const save = () => {
    const next = text.trim();
    setEditing(false);
    if (next === (note ?? "")) return;
    pendingRef.current = next;
    setPending(next);
    setFailed(false);
    // exp_add refuses an empty note; clearing one goes through `note`.
    run(ws, app, next ? "exp_add" : "note", { verstr, note: next });
  };

  if (editing) {
    return (
      <div className="run-note">
        <input
          aria-label="Note"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") setEditing(false);
          }}
          autoFocus
        />
        <button className="primary" onClick={save}>Save note</button>
        <button onClick={() => setEditing(false)}>Cancel</button>
      </div>
    );
  }

  // A request that never reached the server leaves the old note standing.
  const shown = error ? note : pending ?? note;
  return (
    <div className="run-note">
      {shown && <span>{shown}</span>}
      <button
        className="link"
        onClick={() => { setText(shown ?? ""); setEditing(true); }}
      >
        {shown ? "✎ edit note" : "＋ add note"}
      </button>
      {(error || failed) && <span className="error">{error || "note not saved"}</span>}
    </div>
  );
}
