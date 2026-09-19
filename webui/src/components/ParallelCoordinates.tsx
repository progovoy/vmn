import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";

interface Props {
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  onBrush?: (indices: number[] | null) => void;
}
interface DimExtent { min: number; max: number }

const PAD = 20, CHART_H = 300, LABEL_H = 24, SVG_H = CHART_H + LABEL_H;
const CANVAS_THRESHOLD = 500;
const PALETTE = [
  "var(--minor)", "var(--hotfix)", "var(--patch)",
  "var(--pre)", "var(--major)", "var(--series-4)",
];

function numVal(row: ExperimentRow, dim: string, mCols: string[]): number | null {
  const v = mCols.includes(dim) ? row.metrics[dim] : row.user_meta?.[dim];
  return typeof v === "number" ? v : null;
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
  ext: Record<string, DimExtent>, plotH: number, bDim: number, bRange: [number, number]): boolean {
  const v = numVal(row, dims[bDim], mCols);
  if (v === null) return false;
  const y = yScale(v, ext[dims[bDim]], plotH);
  const lo = Math.min(bRange[0], bRange[1]), hi = Math.max(bRange[0], bRange[1]);
  return y >= lo && y <= hi;
}

function SvgRenderer({ rows, dims, mCols, ext, xs, plotH, w, bDim, bRange, bRef,
  onStart, onMove, onEnd }: {
  rows: ExperimentRow[]; dims: string[]; mCols: string[];
  ext: Record<string, DimExtent>; xs: number[]; plotH: number; w: number;
  bDim: number | null; bRange: [number, number] | null;
  bRef: React.RefObject<number | null>;
  onStart: (d: number, y: number) => void; onMove: (y: number) => void; onEnd: () => void;
}) {
  return (
    <svg width={w} height={SVG_H} style={{ display: "block" }}>
      {dims.map((d, i) => (
        <g key={d}>
          <line data-testid="axis" x1={xs[i]} y1={PAD} x2={xs[i]} y2={PAD + plotH}
            stroke="var(--line)" strokeWidth={1} />
          <text x={xs[i]} y={SVG_H - 4} textAnchor="middle" fontSize={10} fill="var(--text-2)">{d}</text>
          {bDim === i && bRange && (
            <rect x={xs[i] - 6} y={Math.min(bRange[0], bRange[1])} width={12}
              height={Math.abs(bRange[1] - bRange[0])} fill="var(--accent)" opacity={0.25} rx={2} />
          )}
          <rect data-testid="brush-area" x={xs[i] - 12} y={PAD} width={24} height={plotH}
            fill="transparent" style={{ cursor: "crosshair" }}
            onMouseDown={(e) => onStart(i, e.clientY)}
            onMouseMove={(e) => { if (bRef.current !== null) onMove(e.clientY); }}
            onMouseUp={onEnd} />
        </g>
      ))}
      {rows.map((r, ri) => {
        const p = buildPath(r, dims, mCols, ext, xs, plotH);
        if (!p) return null;
        const dim = bDim !== null && bRange !== null && !inBrush(r, dims, mCols, ext, plotH, bDim, bRange);
        return <path key={ri} data-testid="row-line" d={p} fill="none"
          stroke={PALETTE[ri % PALETTE.length]} strokeWidth={1.5} opacity={dim ? 0.1 : 0.8} />;
      })}
    </svg>
  );
}

function CanvasRenderer({ rows, dims, mCols, ext, xs, plotH, w }: {
  rows: ExperimentRow[]; dims: string[]; mCols: string[];
  ext: Record<string, DimExtent>; xs: number[]; plotH: number; w: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext("2d"); if (!ctx) return;
    ctx.clearRect(0, 0, w, CHART_H);
    for (let ri = 0; ri < rows.length; ri++) {
      ctx.save(); ctx.strokeStyle = PALETTE[ri % PALETTE.length];
      ctx.globalAlpha = 0.4; ctx.lineWidth = 1; ctx.beginPath();
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
  }, [rows, dims, mCols, ext, xs, plotH, w]);

  return (
    <div>
      <canvas ref={ref} width={w} height={CHART_H} style={{ display: "block" }} />
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

  const [bDim, setBDim] = useState<number | null>(null);
  const [bRange, setBRange] = useState<[number, number] | null>(null);
  const bDimRef = useRef<number | null>(null);
  const bRangeRef = useRef<[number, number] | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const toY = useCallback((cy: number) => {
    const r = wrapRef.current?.getBoundingClientRect();
    return r ? cy - r.top : cy;
  }, []);

  const onStart = useCallback((di: number, cy: number) => {
    const y = toY(cy);
    bDimRef.current = di; bRangeRef.current = [y, y];
    setBDim(di); setBRange([y, y]);
  }, [toY]);

  const onMove = useCallback((cy: number) => {
    const y = toY(cy);
    if (bRangeRef.current) { const n: [number, number] = [bRangeRef.current[0], y]; bRangeRef.current = n; setBRange(n); }
  }, [toY]);

  const onEnd = useCallback(() => {
    const d = bDimRef.current, r = bRangeRef.current;
    if (d !== null && r !== null && onBrush) {
      const idx: number[] = [];
      for (let i = 0; i < rows.length; i++) if (inBrush(rows[i], dims, metricCols, ext, plotH, d, r)) idx.push(i);
      onBrush(idx);
    }
    bDimRef.current = null; bRangeRef.current = null;
    setBDim(null); setBRange(null);
  }, [rows, dims, metricCols, ext, plotH, onBrush]);

  if (dims.length === 0) return null;

  return (
    <div className="card" ref={wrapRef}>
      <div className="eyebrow">parallel coordinates</div>
      {rows.length > CANVAS_THRESHOLD
        ? <CanvasRenderer rows={rows} dims={dims} mCols={metricCols} ext={ext} xs={xs} plotH={plotH} w={w} />
        : <SvgRenderer rows={rows} dims={dims} mCols={metricCols} ext={ext} xs={xs} plotH={plotH} w={w}
            bDim={bDim} bRange={bRange} bRef={bDimRef} onStart={onStart} onMove={onMove} onEnd={onEnd} />
      }
    </div>
  );
}
