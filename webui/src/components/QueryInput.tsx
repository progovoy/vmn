import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { applySuggestion, suggest, type SuggestFacets } from "../util/querySuggest";

const MAX_SUGGESTIONS = 12;

/** The query box with autocomplete: fields (`metrics.<key>`, `params.<key>`,
 *  row fields), operators and connectives, offered for the word at the caret. */
export default function QueryInput({ value, onChange, facets, invalid, placeholder }: {
  value: string;
  onChange: (text: string) => void;
  facets: SuggestFacets;
  invalid?: boolean;
  placeholder?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [caret, setCaret] = useState(value.length);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const pendingCaret = useRef<number | null>(null);

  const options = useMemo(
    () => (open ? suggest(value, caret, facets).slice(0, MAX_SUGGESTIONS) : []),
    [open, value, caret, facets],
  );
  useEffect(() => setActive(0), [options]);

  // Put the caret after an applied suggestion once React wrote the value.
  useEffect(() => {
    if (pendingCaret.current === null || !inputRef.current) return;
    inputRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
    pendingCaret.current = null;
  }, [value]);

  const choose = (choice: string) => {
    const next = applySuggestion(value, caret, choice);
    pendingCaret.current = next.caret;
    setCaret(next.caret);
    onChange(next.text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!options.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a + step + options.length) % options.length);
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const syncCaret = () => setCaret(inputRef.current?.selectionStart ?? value.length);

  return (
    <div className="query-input">
      <input
        ref={inputRef}
        type="text"
        className="mono"
        aria-label="Filter query"
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={options.length > 0}
        aria-activedescendant={options.length ? `${listId}-${active}` : undefined}
        aria-invalid={Boolean(invalid)}
        placeholder={placeholder}
        value={value}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => {
          setCaret(e.target.selectionStart ?? e.target.value.length);
          setOpen(true);
          onChange(e.target.value);
        }}
        onKeyDown={onKeyDown}
        onKeyUp={syncCaret}
        onClick={syncCaret}
        onBlur={() => setOpen(false)}
      />
      {options.length > 0 && (
        <ul className="query-suggest" role="listbox" id={listId}>
          {options.map((o, i) => (
            <li
              key={o}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => { e.preventDefault(); choose(o); }}
            >
              {o}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
