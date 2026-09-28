import { memo } from "react";

/** One entry per run: hover highlights its curves, click switches them off. */
function OverlayLegend({ runs, colorOf, hidden, onToggle, onHover }: {
  runs: string[];
  colorOf: (run: string) => string;
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
          <button
            key={v}
            className="link"
            aria-pressed={on}
            onClick={() => onToggle(v)}
            onMouseEnter={() => onHover(on ? v : null)}
            style={{
              display: "flex", alignItems: "center", gap: 6, padding: "2px 6px",
              color: on ? "var(--text-2)" : "var(--text-3)",
              textDecoration: on ? "none" : "line-through",
            }}
          >
            <span style={{ width: 14, height: 3, borderRadius: 2, background: colorOf(v), opacity: on ? 1 : 0.3 }} />
            {v}
          </button>
        );
      })}
    </div>
  );
}

export default memo(OverlayLegend);
