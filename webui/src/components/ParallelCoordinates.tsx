import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { paramValue, runColor } from "../util";

interface Props {
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  /** Row indices inside the brush, or null when the brush is cleared. */
  onBrush?: (indices: number[] | null) => void;
}
interface DimExtent { min: number; max: number }
interface Brush { dim: number; range: [number, number] }

const PAD = 20, CHART_H = 300, LABEL_H = 24, SVG_H = CHART_H + LABEL_H;
const CANVAS_THRESHOLD = 500;
/** A drag shorter than this is a click: it clears the brush. */
const MIN_BRUSH_PX = 3;

function numVal(row: ExperimentRow, dim: string, mCols: string[]): number | null {
  const v = mCols.includes(dim) ? row.metrics[dim] : paramValue(row, dim);
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function extents(rows: ExperimentRow[], dims: string[], mCols: string[]) {
  const out: Record<string, DimExtent> = {};
  for (const d of dims) {
    let lo = Infinity, hi = -Infinity;
    for (const r of rows) { const v = numVal(r, d, mCols); if (v !== null) { if (v < lo) lo = v; if (v > hi) hi = v; } }
    out[d] = { min: lo === Infinity ? 0 : lo, max: hi === -Infinity ? 1 : hi };
  }
  return out;
}

function yScale(val: number, ext: DimExtent, plotH: number): number {
  const t = ext.max === ext.min ? 0.5 : (val - ext.min) / (ext.max - ext.min);
  return PAD + plotH - t * plotH;
}

function buildPath(row: ExperimentRow, dims: string[], mCols: string[],
  ext: Record<string, DimExtent>, xs: number[], plotH: number): string {
  const s: string[] = []; let on = false;
  for (let i = 0; i < dims.length; i++) {
    const v = numVal(row, dims[i], mCols);
    if (v === null) { on = false; continue; }
    s.push(`${on ? "L" : "M"}${xs[i]},${yScale(v, ext[dims[i]], plotH)}`);
    on = true;
  }
  return s.join("");
}

function inBrush(row: ExperimentRow, dims: string[], mCols: string[],
  ext: Record<string, DimExtent>, plotH: number, brush: Brush): boolean {
  const v = numVal(row, dims[brush.dim], mCols);
  if (v === null) return false;
  const y = yScale(v, ext[dims[brush.dim]], plotH);
  const lo = Math.min(...brush.range), hi = Math.max(...brush.range);
  return y >= lo && y <= hi;
}

interface Geometry {
  rows: ExperimentRow[]; dims: string[]; mCols: string[];
  ext: Record<string, DimExtent>; xs: number[]; plotH: number; w: number;
}
interface BrushHandlers {
  brush: Brush | null;
  onStart: (d: number, y: number) => void; onMove: (y: number) => void; onEnd: () => void;
}

/** The per-axis hit areas plus the visible brush rectangle. */
function BrushAreas({ dims, xs, plotH, brush, onStart, onMove, onEnd }:
  Pick<Geometry, "dims" | "xs" | "plotH"> & BrushHandlers) {
  return (
    <>
      {dims.map((d, i) => (
        <g key={d}>
          {brush?.dim === i && (
            <rect x={xs[i] - 6} y={Math.min(...brush.range)} width={12}
              height={Math.abs(brush.range[1] - brush.range[0])} fill="var(--accent)" opacity={0.25} rx={2} />
          )}
          <rect data-testid="brush-area" x={xs[i] - 12} y={PAD} width={24} height={plotH}
            fill="transparent" style={{ cursor: "crosshair" }}
            onMouseDown={(e) => onStart(i, e.clientY)}
            onMouseMove={(e) => onMove(e.clientY)}
            onMouseUp={onEnd} />
        </g>
      ))}
    </>
  );
}

function SvgRenderer(props: Geometry & BrushHandlers & { selected: Set<number> | null }) {
  const { rows, dims, mCols, ext, xs, plotH, w, selected } = props;
  return (
    <svg width={w} height={SVG_H} style={{ display: "block" }}>
      {dims.map((d, i) => (
        <g key={d}>
          <line data-testid="axis" x1={xs[i]} y1={PAD} x2={xs[i]} y2={PAD + plotH}
            stroke="var(--line)" strokeWidth={1} />
          <text x={xs[i]} y={SVG_H - 4} textAnchor="middle" fontSize={10} fill="var(--text-2)">{d}</text>
        </g>
      ))}
      {rows.map((r, ri) => {
        const p = buildPath(r, dims, mCols, ext, xs, plotH);
        if (!p) return null;
        const dim = selected !== null && !selected.has(ri);
        return <path key={ri} data-testid="row-line" d={p} fill="none"
          stroke={runColor(ri % 6)} strokeWidth={1.5} opacity={dim ? 0.1 : 0.8} />;
      })}
      <BrushAreas {...props} />
    </svg>
  );
}

function CanvasRenderer(props: Geometry & BrushHandlers & { selected: Set<number> | null }) {
  const { rows, dims, mCols, ext, xs, plotH, w, selected } = props;
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext("2d"); if (!ctx) return;
    ctx.clearRect(0, 0, w, CHART_H);
    for (let ri = 0; ri < rows.length; ri++) {
      ctx.save(); ctx.strokeStyle = runColor(ri % 6);
      ctx.globalAlpha = selected !== null && !selected.has(ri) ? 0.04 : 0.4;
      ctx.lineWidth = 1; ctx.beginPath();
      let on = false;
      for (let di = 0; di < dims.length; di++) {
        const v = numVal(rows[ri], dims[di], mCols);
        if (v === null) { on = false; continue; }
        const x = xs[di], y = yScale(v, ext[dims[di]], plotH);
        if (!on) { ctx.moveTo(x, y); on = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke(); ctx.restore();
    }
    for (let i = 0; i < dims.length; i++) {
      ctx.beginPath(); ctx.strokeStyle = "gray"; ctx.lineWidth = 1; ctx.globalAlpha = 0.5;
      ctx.moveTo(xs[i], PAD); ctx.lineTo(xs[i], PAD + plotH); ctx.stroke();
    }
  }, [rows, dims, mCols, ext, xs, plotH, w, selected]);

  return (
    <div>
      <div style={{ position: "relative", width: w, height: CHART_H }}>
        <canvas ref={ref} width={w} height={CHART_H} style={{ display: "block" }} />
        <svg width={w} height={CHART_H} style={{ position: "absolute", inset: 0 }}>
          <BrushAreas {...props} />
        </svg>
      </div>
      <svg width={w} height={LABEL_H} style={{ display: "block" }}>
        {dims.map((d, i) => (
          <text key={d} data-testid="axis" x={xs[i]} y={16}
            textAnchor="middle" fontSize={10} fill="var(--text-2)">{d}</text>
        ))}
      </svg>
    </div>
  );
}

export default function ParallelCoordinates({ rows, metricCols, paramCols, schema: _schema, onBrush }: Props) {
  const dims = useMemo(() => [...metricCols, ...paramCols], [metricCols, paramCols]);
  const ext = useMemo(() => extents(rows, dims, metricCols), [rows, dims, metricCols]);
  const w = Math.max(dims.length * 100, 300);
  const plotH = CHART_H - PAD - PAD;
  const xs = useMemo(() => {
    if (dims.length <= 1) return [w / 2];
    return dims.map((_, i) => 40 + i * ((w - 80) / (dims.length - 1)));
  }, [dims, w]);

  // The brush persists after mouseup — it is a filter, not a transient hover.
  const [brush, setBrush] = useState<Brush | null>(null);
  const dragRef = useRef<Brush | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const toY = useCallback((cy: number) => {
    const r = wrapRef.current?.getBoundingClientRect();
    return r ? cy - r.top : cy;
  }, []);

  const onStart = useCallback((dim: number, cy: number) => {
    const y = toY(cy);
    dragRef.current = { dim, range: [y, y] };
    setBrush(dragRef.current);
  }, [toY]);

  const onMove = useCallback((cy: number) => {
    const d = dragRef.current;
    if (!d) return;
    dragRef.current = { dim: d.dim, range: [d.range[0], toY(cy)] };
    setBrush(dragRef.current);
  }, [toY]);

  const selected = useMemo(() => {
    if (!brush || Math.abs(brush.range[1] - brush.range[0]) < MIN_BRUSH_PX) return null;
    const idx = new Set<number>();
    for (let i = 0; i < rows.length; i++) if (inBrush(rows[i], dims, metricCols, ext, plotH, brush)) idx.add(i);
    return idx;
  }, [brush, rows, dims, metricCols, ext, plotH]);

  const clear = useCallback(() => {
    dragRef.current = null;
    setBrush(null);
    onBrush?.(null);
  }, [onBrush]);

  const onEnd = useCallback(() => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d) return;
    if (Math.abs(d.range[1] - d.range[0]) < MIN_BRUSH_PX) { clear(); return; }
    const idx: number[] = [];
    for (let i = 0; i < rows.length; i++) if (inBrush(rows[i], dims, metricCols, ext, plotH, d)) idx.push(i);
    onBrush?.(idx);
  }, [rows, dims, metricCols, ext, plotH, onBrush, clear]);

  if (dims.length === 0) return null;

  const geometry = { rows, dims, mCols: metricCols, ext, xs, plotH, w };
  const handlers = { brush, onStart, onMove, onEnd, selected };
  return (
    <div className="card" ref={wrapRef}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div className="eyebrow">parallel coordinates</div>
        {selected && (
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>
            {selected.size} of {rows.length} selected ·{" "}
            <button className="link" onClick={clear}>clear</button>
          </span>
        )}
      </div>
      {rows.length > CANVAS_THRESHOLD
        ? <CanvasRenderer {...geometry} {...handlers} />
        : <SvgRenderer {...geometry} {...handlers} />
      }
    </div>
  );
}
