import { useState } from "react";
import { resolveText, type Choice, type MergeChunk } from "./merge";

const CHOICES: Choice[] = ["theirs", "yours", "both", "base"];

interface Props {
  chunks: MergeChunk[];
  theirsAuthor?: string | null;
  onSave: (body: string) => void;
  onCancel: () => void;
}

function Hunk({ n, c, choice, onChoose }: {
  n: number; c: Extract<MergeChunk, { kind: "conflict" }>; choice: Choice; onChoose: (c: Choice) => void;
}) {
  return (
    <fieldset className="card">
      <legend>Hunk {n + 1}</legend>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        {(["base", "theirs", "yours"] as const).map((side) => (
          <div key={side}><b>{side}</b><pre className="mono">{c[side].join("\n")}</pre></div>
        ))}
      </div>
      {CHOICES.map((ch) => (
        <label key={ch} style={{ marginRight: 8 }}>
          <input type="radio" name={`hunk-${n}`} aria-label={`Hunk ${n + 1}: ${ch}`}
            checked={choice === ch} onChange={() => onChoose(ch)} /> {ch}
        </label>
      ))}
    </fieldset>
  );
}

/** Per-hunk choice between base/theirs/yours plus a manual edit of the result. */
export default function ConflictResolve({ chunks, theirsAuthor, onSave, onCancel }: Props) {
  const conflicts = chunks.filter((c) => c.kind === "conflict");
  const [choices, setChoices] = useState<Choice[]>(conflicts.map(() => "yours"));
  const [text, setText] = useState(() => resolveText(chunks, choices));
  const choose = (n: number, ch: Choice) => {
    const next = choices.map((c, i) => (i === n ? ch : c));
    setChoices(next);
    setText(resolveText(chunks, next));
  };
  return (
    <section aria-label="Resolve conflicts" className="card">
      <h3>Conflicting edits{theirsAuthor ? ` (theirs by ${theirsAuthor})` : ""}</h3>
      {conflicts.map((c, n) => (
        <Hunk key={n} n={n} c={c} choice={choices[n]} onChoose={(ch) => choose(n, ch)} />
      ))}
      <textarea aria-label="Merged result" className="mono" style={{ width: "100%", minHeight: "30vh" }}
        value={text} onChange={(e) => setText(e.target.value)} />
      <button type="button" className="btn" onClick={() => onSave(text)}>Save resolved</button>
      <button type="button" className="btn" onClick={onCancel}>Cancel</button>
    </section>
  );
}
