import { memo } from "react";
import CopyRefButton from "./CopyRefButton";

const asIs = (run: string) => run;

/** One entry per run, named by *labelOf* (`@N name`) with the verstr in its
 *  title and a copy button: hover highlights its curves, click switches
 *  them off. */
function OverlayLegend({ runs, colorOf, labelOf = asIs, hidden, onToggle, onHover }: {
  runs: string[];
  colorOf: (run: string) => string;
  labelOf?: (run: string) => string;
  hidden: ReadonlySet<string>;
  onToggle: (run: string) => void;
  onHover: (run: string | null) => void;
}) {
  return (
    <div
      style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, flexWrap: "wrap" }}
      onMouseLeave={() => onHover(null)}
    >
      {runs.map((v) => {
        const on = !hidden.has(v);
        return (
          <span key={v} style={{ display: "inline-flex", alignItems: "center" }}>
            <button
              className="link"
              aria-pressed={on}
              title={v}
              onClick={() => onToggle(v)}
              onMouseEnter={() => onHover(on ? v : null)}
              style={{
                display: "flex", alignItems: "center", gap: 6, padding: "2px 2px 2px 6px",
                color: on ? "var(--text-2)" : "var(--text-3)",
                textDecoration: on ? "none" : "line-through",
              }}
            >
              <span style={{ width: 14, height: 3, borderRadius: 2, background: colorOf(v), opacity: on ? 1 : 0.3 }} />
              {labelOf(v)}
            </button>
            <CopyRefButton text={v} />
          </span>
        );
      })}
    </div>
  );
}

export default memo(OverlayLegend);
