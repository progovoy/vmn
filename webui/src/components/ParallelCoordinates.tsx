import { memo, useCallback, useMemo, useRef, useState } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { metricGoal } from "../util";
import {
  buildAxes, buildMatrix, colorScale, selectRows, targetTs, yFromT, type Axis, type Brushes,
} from "../util/parallelData";
import ParallelCanvas, { type PlotGeometry } from "./ParallelCanvas";
import { useAxisBrush } from "./useAxisBrush";

interface Props {
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  /** Row indices inside every brush, or null when no brush is active. */
  onBrush?: (indices: number[] | null) => void;
}

const PAD = 20, CHART_H = 300, LABEL_H = 24, PLOT_H = CHART_H - 2 * PAD;
const CANVAS_THRESHOLD = 500;
/** Colour steps: few distinct strokes lets the canvas batch one path per colour. */
const COLOR_STEPS = 31;
const NO_TARGET = "var(--text-3)";

function rowPath(m: Float64Array, nDims: number, r: number, xs: number[]): string {
  const s: string[] = [];
  let on = false;
  for (let d = 0; d < nDims; d++) {
    const t = m[r * nDims + d];
    if (Number.isNaN(t)) { on = false; continue; }
    s.push(`${on ? "L" : "M"}${xs[d]},${yFromT(t, PAD, PLOT_H)}`);
    on = true;
  }
  return s.join("");
}

function CategoryTicks({ axes, xs }: { axes: Axis[]; xs: number[] }) {
  return (
    <>
      {axes.map((a, i) => a.kind === "cat" && a.categories.map((c, ci) => (
        <text key={`${a.name}:${c}`} x={xs[i] + 5} fontSize={9} fill="var(--text-3)"
          y={yFromT(a.categories.length === 1 ? 0.5 : ci / (a.categories.length - 1), PAD, PLOT_H) + 3}>
          {c}
        </text>
      )))}
    </>
  );
}

function BrushAreas({ xs, brushes, onStart }: {
  xs: number[]; brushes: Brushes; onStart: (dim: number, clientY: number) => void;
}) {
  return (
    <>
      {xs.map((x, i) => {
        const b = brushes.get(i);
        const y0 = b ? yFromT(Math.max(...b), PAD, PLOT_H) : 0;
        return (
          <g key={i}>
            {b && (
              <rect x={x - 6} y={y0} width={12} rx={2} fill="var(--accent)" opacity={0.25}
                height={yFromT(Math.min(...b), PAD, PLOT_H) - y0} />
            )}
            <rect data-testid="brush-area" x={x - 12} y={PAD} width={24} height={PLOT_H}
              fill="transparent" style={{ cursor: "crosshair" }}
              onMouseDown={(e) => { e.preventDefault(); onStart(i, e.clientY); }} />
          </g>
        );
      })}
    </>
  );
}

type RenderProps = PlotGeometry & { axes: Axis[]; brushes: Brushes; onStart: (d: number, y: number) => void };

function SvgPlot(p: RenderProps) {
  const { matrix, nDims, xs, w, strokes, selected, axes } = p;
  return (
    <svg width={w} height={CHART_H + LABEL_H} style={{ display: "block" }}>
      {axes.map((a, i) => (
        <g key={a.name}>
          <line data-testid="axis" x1={xs[i]} y1={PAD} x2={xs[i]} y2={PAD + PLOT_H} stroke="var(--line-2)" />
          <text x={xs[i]} y={CHART_H + LABEL_H - 4} textAnchor="middle" fontSize={10} fill="var(--text-2)">{a.name}</text>
        </g>
      ))}
      {strokes.map((stroke, r) => {
        const d = rowPath(matrix, nDims, r, xs);
        return d ? <path key={r} data-testid="row-line" d={d} fill="none" stroke={stroke} strokeWidth={1.5}
          opacity={selected && !selected.has(r) ? 0.08 : 0.85} /> : null;
      })}
      <CategoryTicks axes={axes} xs={xs} />
      <BrushAreas {...p} />
    </svg>
  );
}

function CanvasPlot(p: RenderProps) {
  return (
    <div>
      <div style={{ position: "relative", width: p.w, height: CHART_H }}>
        <ParallelCanvas {...p} />
        <svg width={p.w} height={CHART_H} style={{ position: "absolute", inset: 0 }}>
          <CategoryTicks axes={p.axes} xs={p.xs} />
          <BrushAreas {...p} />
        </svg>
      </div>
      <svg width={p.w} height={LABEL_H} style={{ display: "block" }}>
        {p.axes.map((a, i) => (
          <text key={a.name} data-testid="axis" x={p.xs[i]} y={16} textAnchor="middle" fontSize={10}
            fill="var(--text-2)">{a.name}</text>
        ))}
      </svg>
    </div>
  );
}

const defaultTarget = (metricCols: string[], schema: MetricsSchema | null) =>
  metricCols.find((m) => schema?.[m]?.primary) ?? metricCols[0] ?? null;

function ParallelCoordinates({ rows, metricCols, paramCols, schema, onBrush }: Props) {
  const dims = useMemo(() => [...metricCols, ...paramCols], [metricCols, paramCols]);
  const axes = useMemo(() => buildAxes(rows, dims, metricCols), [rows, dims, metricCols]);
  const matrix = useMemo(() => buildMatrix(rows, dims, metricCols, axes), [rows, dims, metricCols, axes]);
  const w = Math.max(dims.length * 100, 300);
  const xs = useMemo(() => (dims.length <= 1 ? [w / 2]
    : dims.map((_, i) => 40 + i * ((w - 80) / (dims.length - 1)))), [dims, w]);

  const [chosen, setChosen] = useState<string | null>(null);
  const target = chosen !== null && metricCols.includes(chosen) ? chosen : defaultTarget(metricCols, schema);
  const strokes = useMemo(() => {
    if (!target) return rows.map(() => NO_TARGET);
    return targetTs(rows, target, metricGoal(schema, target)).map((t) =>
      t === null ? NO_TARGET : colorScale(Math.round(t * COLOR_STEPS) / COLOR_STEPS));
  }, [rows, target, schema]);

  const plotRef = useRef<HTMLDivElement>(null);
  const toY = useCallback((cy: number) => cy - (plotRef.current?.getBoundingClientRect().top ?? 0), []);
  const latest = useRef({ matrix, nDims: dims.length, onBrush });
  latest.current = { matrix, nDims: dims.length, onBrush };
  const commit = useCallback((b: Brushes) => {
    const { matrix: m, nDims, onBrush: emit } = latest.current;
    emit?.(selectRows(m, nDims, b));
  }, []);
  const { brushes, onStart, clear } = useAxisBrush(toY, PAD, PLOT_H, commit);

  const selectedList = useMemo(() => selectRows(matrix, dims.length, brushes), [matrix, dims.length, brushes]);
  const selected = useMemo(() => (selectedList ? new Set(selectedList) : null), [selectedList]);

  const clearAll = useCallback(() => { clear(); onBrush?.(null); }, [clear, onBrush]);

  if (dims.length === 0) return null;

  const plot: RenderProps = {
    matrix, nDims: dims.length, xs, top: PAD, plotH: PLOT_H, w, h: CHART_H,
    strokes, selected, axes, brushes, onStart,
  };
  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div className="eyebrow">parallel coordinates</div>
        {target && (
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
            color by
            <select aria-label="color by" value={target} onChange={(e) => setChosen(e.target.value)}>
              {metricCols.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        )}
        {selectedList && (
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>
            {selectedList.length} of {rows.length} selected ·{" "}
            <button className="link" onClick={clearAll}>clear</button>
          </span>
        )}
      </div>
      <div ref={plotRef} style={{ overflowX: "auto" }}>
        {rows.length > CANVAS_THRESHOLD ? <CanvasPlot {...plot} /> : <SvgPlot {...plot} />}
      </div>
    </div>
  );
}

/** Memoized: the leaderboard re-polls, and identical rows must not redraw. */
export default memo(ParallelCoordinates);
