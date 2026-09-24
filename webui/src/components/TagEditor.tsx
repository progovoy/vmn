import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { rowsPrefix, runKey, type RowsData } from "../queries";
import type { ExperimentDetail } from "../types";
import { applyTagEdit, parseTag, tagLabel, type Tags } from "../util/tags";
import { useJob } from "./ui";

interface Edit { set: Tags; remove: string[] }

/** A run's tags, editable in place (`vmn exp tag`). Like NoteEditor: the edit
 *  shows at once, the caches take it once the job succeeds, and a failed job
 *  puts the old tags back. */
export default function TagEditor({ ws, app, verstr, tags }: {
  ws: string; app: string; verstr: string; tags: Tags | undefined;
}) {
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [pending, setPending] = useState<Tags | null>(null);
  const [failed, setFailed] = useState(false);
  // What the last successful job wrote, until the tags prop catches up.
  const [saved, setSaved] = useState<Tags | null>(null);
  useEffect(() => setSaved(null), [tags]);
  // The job's completion callback outlives the render that started it.
  const editRef = useRef<Edit | null>(null);

  const commit = ({ set, remove }: Edit) => {
    client.setQueryData<ExperimentDetail>(runKey(ws, app, verstr), (d) =>
      d && { ...d, metadata: { ...d.metadata, tags: applyTagEdit(d.metadata.tags as Tags, set, remove) } });
    client.setQueriesData<RowsData>({ queryKey: rowsPrefix(ws, app) }, (data) =>
      data && {
        ...data,
        rows: data.rows.map((r) => (r.verstr === verstr ? { ...r, tags: applyTagEdit(r.tags, set, remove) } : r)),
      });
  };
  const { error, run } = useJob((j) => {
    if (j.status === "succeeded" && editRef.current) {
      commit(editRef.current);
      setSaved(applyTagEdit(tags, editRef.current.set, editRef.current.remove));
    }
    setFailed(j.status !== "succeeded");
    editRef.current = null;
    setPending(null);
  });

  const busy = pending !== null;
  const shown = (error ? null : pending) ?? saved ?? tags ?? {};

  const submit = (edit: Edit) => {
    editRef.current = edit;
    setPending(applyTagEdit(tags, edit.set, edit.remove));
    setFailed(false);
    run(ws, app, "exp_tag", { verstr, ...edit });
  };

  const add = () => {
    const tag = parseTag(text);
    if (!tag) { setInvalid(true); return; }
    setAdding(false);
    setText("");
    setInvalid(false);
    submit({ set: { [tag.key]: tag.value }, remove: [] });
  };

  return (
    <div className="tag-editor">
      {Object.entries(shown).map(([k, v]) => (
        <span key={k} className="tag-chip">
          {tagLabel(k, v)}
          <button
            className="tag-remove" aria-label={`Remove tag ${k}`} disabled={busy}
            onClick={() => submit({ set: {}, remove: [k] })}
          >×</button>
        </span>
      ))}
      {adding ? (
        <>
          <input
            aria-label="New tag" placeholder="key=value" value={text} autoFocus
            onChange={(e) => { setText(e.target.value); setInvalid(false); }}
            onKeyDown={(e) => {
              if (e.key === "Enter") add();
              if (e.key === "Escape") setAdding(false);
            }}
          />
          <button className="primary" onClick={add}>Add</button>
          <button onClick={() => setAdding(false)}>Cancel</button>
        </>
      ) : (
        <button className="link" disabled={busy} onClick={() => setAdding(true)}>+ tag</button>
      )}
      {invalid && <span className="error" role="alert">use key=value (no spaces in key, no leading -)</span>}
      {(error || failed) && <span className="error">{error || "tags not saved"}</span>}
    </div>
  );
}
