import { useCallback, useId, useState, type ReactNode } from "react";
import { Icon } from "./shell/icons";
import "./Disclosure.css";

/** localStorage key of every disclosure's open/closed choice, `{id: open}`. */
export const DISCLOSURE_KEY = "vmn-exp:disclosures";

function readChoices(): Record<string, boolean> {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(DISCLOSURE_KEY) ?? "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, boolean> : {};
  } catch {
    return {};
  }
}

function writeChoice(id: string, open: boolean) {
  try {
    localStorage.setItem(DISCLOSURE_KEY, JSON.stringify({ ...readChoices(), [id]: open }));
  } catch { /* storage disabled: the choice lasts this page only */ }
}

/** Open state of disclosure *id*: the user's stored choice, else *defaultOpen*
 *  (which may change, e.g. once comments load, until the user chooses). */
export function useDisclosure(id: string, defaultOpen: boolean): [boolean, () => void] {
  const [chosen, setChosen] = useState<boolean | undefined>(() => readChoices()[id]);
  const open = chosen ?? defaultOpen;
  const toggle = useCallback(() => {
    setChosen(!open);
    writeChoice(id, !open);
  }, [id, open]);
  return [open, toggle];
}

/** A collapsible page section: an h2 whose button opens it (the WAI
 *  disclosure pattern, so screen readers still list the heading). Closed, it
 *  shows *preview* if given; a *lazy* body mounts only while open. */
export default function Disclosure({ id, title, defaultOpen = false, preview, lazy, className, children }: {
  id: string;
  title: string;
  defaultOpen?: boolean;
  preview?: ReactNode;
  lazy?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const [open, toggle] = useDisclosure(id, defaultOpen);
  const uid = useId();
  const titleId = `${uid}-title`;
  const bodyId = `${uid}-body`;
  return (
    <section className={`card disclosure${className ? ` ${className}` : ""}`} aria-labelledby={titleId}
      data-open={open}>
      <h2 className="section-title disclosure-title">
        <button type="button" id={titleId} className="disclosure-toggle"
          aria-expanded={open} aria-controls={bodyId} onClick={toggle}>
          <Icon name={open ? "chevron-down" : "chevron-right"} size={14} />
          {title}
        </button>
      </h2>
      {!open && preview && <div className="disclosure-preview">{preview}</div>}
      <div id={bodyId} className="disclosure-body" hidden={!open}>
        {lazy && !open ? null : children}
      </div>
    </section>
  );
}
