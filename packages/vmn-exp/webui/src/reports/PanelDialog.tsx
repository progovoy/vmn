import { useState, type FormEvent } from "react";
import QueryInput from "../components/QueryInput";
import { validate, type PanelType } from "./panelSpec";
import { queryProblem } from "./panelBlocks";

type Spec = Record<string, unknown>;
type FieldKind = "text" | "list" | "number" | "step";
interface Field { key: string; label: string; kind: FieldKind }

const f = (key: string, label: string, kind: FieldKind = "text"): Field => ({ key, label, kind });

const TYPE_FIELDS: Record<PanelType, Field[]> = {
  curves: [f("keys", "Keys", "list")],
  leaderboard: [f("columns", "Columns", "list"), f("params", "Params", "list")],
  bar: [f("metric", "Metric")],
  scatter: [f("x", "X"), f("y", "Y")],
  parallel: [f("columns", "Columns", "list")],
  importance: [f("metric", "Metric")],
  grouped: [f("group_by", "Group by"), f("metric", "Metric")],
  media: [f("key", "Key"), f("step", "Step", "step")],
  table: [f("path", "Path")],
  histogram: [f("key", "Key")],
  lineage: [f("depth", "Depth", "number")],
  run: [],
};
const TYPES = Object.keys(TYPE_FIELDS) as PanelType[];

const splitList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const newId = () => "p" + Math.random().toString(36).slice(2, 6);

function toText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return value === undefined || value === null ? "" : String(value);
}

function fromText(kind: FieldKind, text: string): unknown {
  const t = text.trim();
  if (!t) return undefined;
  if (kind === "list") return splitList(t);
  if (kind === "number" || (kind === "step" && t !== "last")) return Number(t);
  return t;
}

function initialValues(spec: Spec): Record<string, string> {
  const out: Record<string, string> = {};
  for (const fields of Object.values(TYPE_FIELDS)) for (const fd of fields) out[fd.key] = toText(spec[fd.key]);
  return out;
}

interface Form { type: PanelType; app: string; pinned: boolean; query: string; verstrs: string; values: Record<string, string> }

function initialForm(spec: Spec): Form {
  const runs = (spec.runs ?? {}) as Spec;
  return {
    type: TYPES.includes(spec.type as PanelType) ? (spec.type as PanelType) : "bar",
    app: toText(spec.app),
    pinned: Array.isArray(runs.verstrs),
    query: toText(runs.query),
    verstrs: toText(runs.verstrs),
    values: initialValues(spec),
  };
}

function buildSpec(initial: Spec | undefined, form: Form): Spec {
  const prevRuns = (initial?.runs ?? {}) as Spec;
  const runs = form.pinned
    ? { verstrs: splitList(form.verstrs) }
    : { ...("query" in prevRuns ? prevRuns : {}), query: form.query.trim() };
  const spec: Spec = { ...initial, v: 1, id: initial?.id ?? newId(), type: form.type, app: form.app.trim(), runs };
  for (const fd of TYPE_FIELDS[form.type]) {
    const value = fromText(fd.kind, form.values[fd.key] ?? "");
    if (value === undefined) delete spec[fd.key];
    else spec[fd.key] = value;
  }
  return spec;
}

function specErrors(spec: Spec, form: Form): string[] {
  const errors: string[] = [];
  if (!form.app.trim()) errors.push("app is required");
  if (!form.pinned) { const q = queryProblem(form.query); if (q) errors.push(q); }
  const result = validate(spec);
  if (!result.ok) errors.push(result.error);
  return errors;
}

/** Insert-panel dialog; with `initial` it edits that block's spec. */
export default function PanelDialog({ initial, onSubmit, onClose }: {
  initial?: Spec;
  onSubmit: (spec: Spec) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<Form>(() => initialForm(initial ?? {}));
  const [errors, setErrors] = useState<string[]>([]);
  const set = (patch: Partial<Form>) => setForm((prev) => ({ ...prev, ...patch }));
  const setValue = (key: string, text: string) => set({ values: { ...form.values, [key]: text } });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const spec = buildSpec(initial, form);
    const problems = specErrors(spec, form);
    setErrors(problems);
    if (!problems.length) onSubmit(spec);
  };

  return (
    <div className="modal-backdrop">
      <form role="dialog" aria-label={initial ? "Edit panel" : "Insert panel"} className="card modal" onSubmit={submit}>
        <label>Type{" "}
          <select aria-label="Type" value={form.type} onChange={(e) => set({ type: e.target.value as PanelType })}>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>App <input aria-label="App" value={form.app} onChange={(e) => set({ app: e.target.value })} /></label>
        <fieldset>
          <label><input type="radio" aria-label="Query runs" checked={!form.pinned} onChange={() => set({ pinned: false })} /> query</label>
          <label><input type="radio" aria-label="Pinned runs" checked={form.pinned} onChange={() => set({ pinned: true })} /> pinned</label>
          {form.pinned
            ? <input aria-label="Verstrs" className="mono" placeholder="verstr, verstr" value={form.verstrs}
                onChange={(e) => set({ verstrs: e.target.value })} />
            : <QueryInput value={form.query} onChange={(query) => set({ query })} facets={{}}
                invalid={Boolean(form.query) && Boolean(queryProblem(form.query))} />}
        </fieldset>
        {TYPE_FIELDS[form.type].map((fd) => (
          <label key={fd.key}>{fd.label}{" "}
            <input aria-label={fd.label} value={form.values[fd.key] ?? ""} onChange={(e) => setValue(fd.key, e.target.value)} />
          </label>
        ))}
        {errors.map((err) => <div key={err} role="alert" className="error">{err}</div>)}
        <div style={{ display: "flex", gap: 8 }}>
          <button type="submit" className="btn">{initial ? "Update" : "Insert"}</button>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
