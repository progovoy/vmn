import { useCallback, useEffect, useRef, useState } from "react";
import { useDismiss } from "../hooks/useDismiss";
import type { QueryHelpData } from "../util/queryHelp";
import "./QueryHelp.css";

/** Row fields worth naming first; the box's autocomplete knows the rest. */
const RUN_FIELDS = ["status", "branch", "name", "note", "verstr", "author", "kind", "duration_sec"];
const OPERATORS: [string[], string][] = [
  [["=", "!=", "<", "<=", ">", ">="], "compare"],
  [["~", "!~"], "contains, any case"],
  [["in (…)", "not in (…)"], "one of"],
  [["and", "or", "not"], "combine, with ( )"],
  [["= null"], "field missing"],
];
const SHOWN_KEYS = 6;

/** The help's open state; Escape or a press outside *anchor* (the bar and
 *  the panel) closes it, Escape returning focus to the `?`. */
export function useQueryHelp() {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, anchor, trigger);
  return { open, setOpen, close, anchor, trigger };
}
export type QueryHelpState = ReturnType<typeof useQueryHelp>;

/** The `?` beside the query box. */
export function QueryHelpButton({ state }: { state: QueryHelpState }) {
  return (
    <button
      ref={state.trigger}
      type="button"
      className="status-toggle query-help-button"
      aria-label="Query help"
      aria-haspopup="dialog"
      aria-expanded={state.open}
      title="Query help: fields, operators, examples"
      onClick={() => state.setOpen(!state.open)}
    >
      ?
    </button>
  );
}

function Keys({ keys }: { keys: readonly string[] }) {
  const more = keys.length - SHOWN_KEYS;
  return (
    <>
      {keys.slice(0, SHOWN_KEYS).map((k) => <code key={k}>{k}</code>)}
      {more > 0 && <span className="query-help-more">+{more} more</span>}
    </>
  );
}

/** The help: this app's fields, the operators and examples to try (picking
 *  one hands it to *onPick*). */
export function QueryHelpPanel({ data, onPick }: { data: QueryHelpData; onPick: (example: string) => void }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { panel.current?.focus(); }, []);
  return (
    <div ref={panel} className="query-help" role="dialog" aria-label="Query help" tabIndex={-1}>
      <section>
        <h3>Fields</h3>
        {[data.metrics, data.params, data.tags].filter((keys) => keys.length > 0).map((keys) => (
          <div key={keys[0]} className="query-help-keys"><Keys keys={keys} /></div>
        ))}
        <div className="query-help-keys">{RUN_FIELDS.map((f) => <code key={f}>{f}</code>)}</div>
      </section>
      <section>
        <h3>Operators</h3>
        <dl className="query-help-ops">
          {OPERATORS.map(([ops, what]) => (
            <div key={what}>
              <dt>{ops.map((op) => <code key={op}>{op}</code>)}</dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section>
        <h3>Try</h3>
        <ul className="query-help-examples">
          {data.examples.map((e) => (
            <li key={e}><button type="button" className="mono" onClick={() => onPick(e)}>{e}</button></li>
          ))}
        </ul>
      </section>
      <p className="query-help-foot">Anything else you type searches name, verstr, note and branch.</p>
    </div>
  );
}
