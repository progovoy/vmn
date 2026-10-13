/** Where the dashboard reads this workspace from (plan 20 E6): the checkout
 *  and its store, or a store's URI, behind one icon button so the paths stay
 *  out of the primary chrome. */
import { useCallback, useRef, useState } from "react";
import { useDismiss } from "../../hooks/useDismiss";
import { CopyButton } from "../ui";
import { Icon } from "./icons";
import "./Provenance.css";

export interface Source { label: string; value: string }

export default function Provenance({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, trigger);
  if (!sources.length) return null;
  return (
    <span className="prov" ref={box}>
      <button
        ref={trigger} type="button" className="prov-btn" aria-label="Data source" title="Data source"
        aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}
      >
        <Icon name="store" size={13} />
      </button>
      {open && (
        <div className="prov-pop" role="dialog" aria-label="Data source">
          <dl>
            {sources.map((s) => (
              <div className="prov-row" key={s.label}>
                <dt>{s.label}</dt>
                <dd>
                  <span className="mono">{s.value}</span>
                  <CopyButton text={s.value} className="prov-copy" label={`Copy ${s.label}`} />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </span>
  );
}
