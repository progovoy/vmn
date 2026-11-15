import { useEffect, useRef, useState } from "react";
import {
  isPrerelease, MODE_COLOR, PAD_TOP, ROW_H, shortAlias, type Edge, type Node,
} from "./layout";

const R = 6.5;

/** The version DAG as an SVG: a clickable row per node, edges, then dots and labels. */
export function TreeGraph({
  nodes, edges, byVerstr, current, textX, labelEnd, onSelect,
}: {
  nodes: Node[];
  edges: Edge[];
  byVerstr: Record<string, Node>;
  current: Node;
  textX: number;
  labelEnd: number;
  onSelect: (verstr: string) => void;
}) {
  const graphRef = useRef<HTMLDivElement | null>(null);
  const [graphW, setGraphW] = useState(0);

  useEffect(() => {
    const el = graphRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) =>
      setGraphW(entries[0].contentRect.width)
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const width = Math.max(labelEnd + 110, graphW);
  const height = PAD_TOP + nodes.length * ROW_H + 8;

  return (
    <div ref={graphRef} className="card" style={{ flex: "1 1 320px", minWidth: 0, overflowX: "auto", padding: "8px 6px" }}>
      <svg width={width} height={height} style={{ display: "block" }}>
        {nodes.map((n) => (
          <rect
            key={n.verstr}
            className={`tree-row${current.verstr === n.verstr ? " selected" : ""}`}
            x={2} y={n.y - ROW_H / 2} width={width - 4} height={ROW_H} rx={6}
            onClick={() => onSelect(n.verstr)}
          />
        ))}
        {edges.map(([from, to], i) => {
          const a = byVerstr[from];
          const b = byVerstr[to];
          if (!a || !b) return null;
          const active = from === current.verstr || to === current.verstr;
          return (
            <path
              key={i}
              d={`M${a.x},${a.y} C${a.x},${(a.y + b.y) / 2} ${b.x},${(a.y + b.y) / 2} ${b.x},${b.y}`}
              fill="none"
              stroke={active ? "var(--accent)" : "var(--line-2)"}
              strokeWidth={2}
              pointerEvents="none"
            />
          );
        })}
        {nodes.map((n) => {
          const color = MODE_COLOR[n.mode] ?? "var(--text-muted)";
          const hollow = isPrerelease(n.mode);
          return (
            <g key={n.verstr} pointerEvents="none">
              {current.verstr === n.verstr && (
                <circle cx={n.x} cy={n.y} r={R + 4} fill="none"
                  stroke="var(--accent)" strokeWidth={1.5} />
              )}
              <circle
                cx={n.x} cy={n.y} r={R}
                fill={hollow ? "var(--panel)" : color}
                stroke={hollow ? color : "var(--panel)"}
                strokeWidth={2}
              />
              <text x={textX} y={n.y + 4} fontFamily="var(--mono)">
                <tspan fill="var(--text)" fontSize="12.5">{n.verstr}</tspan>
                {n.aliases.length > 0 && (
                  <tspan dx="10" fill="var(--text-3)" fontSize="11">
                    {n.aliases.map((a) => shortAlias(a, n.verstr)).join(" · ")}
                  </tspan>
                )}
                <tspan dx="14" fill="var(--text-3)" fontSize="11.5">{n.branch}</tspan>
              </text>
              <text x={width - 12} y={n.y + 4} fill="var(--text-3)"
                fontSize="11.5" textAnchor="end">
                {n.rel}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
