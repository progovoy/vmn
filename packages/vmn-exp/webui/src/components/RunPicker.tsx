import { useEffect, useId, useState } from "react";
import { api } from "../api";
import type { ExperimentRow } from "../types";
import { useDebounce } from "../hooks/useDebounce";
import { isAbortError, withSignal } from "../requestScope";
import { runSearchQuery } from "../util/searchQuery";

const SUGGESTIONS = 20;

/** A typeahead over the server: suggestions come from a bounded search (the
 *  newest runs until something is typed), never from loading every run. */
export default function RunPicker({ ws, app, value, onChange }: {
  ws: string;
  app: string;
  value: string;
  onChange: (verstr: string) => void;
}) {
  const [text, setText] = useState(value);
  const [options, setOptions] = useState<ExperimentRow[]>([]);
  const typed = useDebounce(text.trim(), 250);
  const listId = useId();

  useEffect(() => setText(value), [value]);

  useEffect(() => {
    const ctrl = new AbortController();
    const search = typed && typed !== value;
    withSignal(ctrl.signal, () =>
      search
        ? api.experimentsPaged(ws, app, { query: runSearchQuery(typed), limit: SUGGESTIONS })
            .then((page) => page.rows)
        : api.recentExperiments(ws, app, SUGGESTIONS)
    )
      .then(setOptions)
      .catch((e) => { if (!isAbortError(e)) setOptions([]); });
    return () => ctrl.abort();
  }, [ws, app, typed, value]);

  const commit = (v: string) => {
    if (v && v !== value) onChange(v);
  };

  return (
    <div className="select-wrap" style={{ display: "inline-block" }}>
      <input
        role="combobox"
        aria-label="experiment"
        className="mono"
        list={listId}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (options.some((o) => o.verstr === e.target.value)) commit(e.target.value);
        }}
        onKeyDown={(e) => { if (e.key === "Enter") commit(text.trim()); }}
        style={{ width: 280, fontFamily: "var(--mono)", fontSize: 12.5 }}
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o.verstr} value={o.verstr}>
            {`@${o.idx}${o.note ? `  ${o.note}` : ""}`}
          </option>
        ))}
      </datalist>
    </div>
  );
}
