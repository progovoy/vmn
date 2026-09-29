import { useState } from "react";
import type { HistogramItem } from "../types";
import { histogramBars, histogramRange } from "../util/media";
import { fmtVal } from "../util";
import { StepSlider } from "./MediaImages";

const W = 320;
const H = 120;
const ROW_H = 12;

function Bars({ item }: { item: HistogramItem }) {
  const [lo, hi] = histogramRange([item]);
  return (
    <svg className="hist-chart" viewBox={`0 0 ${W} ${H + 14}`} width="100%" role="img"
      aria-label={`histogram at step ${item.step}`}>
      {histogramBars(item, W, H).map((b, i) => (
        <rect key={i} className="hist-bar" x={b.x} y={b.y} width={Math.max(b.w - 0.5, 0.5)} height={b.h}>
          <title>{`[${fmtVal(b.lo)}, ${fmtVal(b.hi)}): ${b.count}`}</title>
        </rect>
      ))}
      <text x={0} y={H + 12} className="hist-axis">{fmtVal(lo)}</text>
      <text x={W} y={H + 12} className="hist-axis" textAnchor="end">{fmtVal(hi)}</text>
    </svg>
  );
}

/** Every step as a row on one shared x range, bin opacity by its count. */
function OverTime({ items }: { items: HistogramItem[] }) {
  const range = histogramRange(items);
  return (
    <svg className="hist-chart" viewBox={`0 0 ${W} ${items.length * ROW_H}`} width="100%"
      role="img" aria-label="histogram over time">
      {items.map((item, r) => {
        const bars = histogramBars(item, W, 1, range);
        return (
          <g key={item.step} className="hist-row" transform={`translate(0 ${r * ROW_H})`}>
            <title>{`step ${item.step}`}</title>
            {bars.map((b, i) => (
              <rect key={i} className="hist-cell" x={b.x} width={Math.max(b.w, 0.5)}
                height={ROW_H - 1} fillOpacity={b.h} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

export function HistogramKey({ name, items, total }: {
  name: string; items: HistogramItem[]; total: number;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const [overTime, setOverTime] = useState(false);
  const index = Math.min(picked ?? items.length - 1, items.length - 1);
  const item = items[index];
  return (
    <div className="media-tile">
      <div className="media-tile-head">
        <span className="mono">{name}</span>
        <span className="muted">{overTime ? `${items.length} of ${total} steps` : `step ${item.step}`}</span>
        {items.length > 1 && (
          <button className="link" onClick={() => setOverTime((v) => !v)}>
            {overTime ? "single step" : "over time"}
          </button>
        )}
      </div>
      {overTime ? <OverTime items={items} /> : <Bars item={item} />}
      {!overTime && (
        <StepSlider label={`step of ${name}`} count={items.length} index={index} onChange={setPicked} />
      )}
    </div>
  );
}

/** Logged histograms: one chart per key for a chosen step, or all steps. */
export default function MediaHistograms({ histograms, totals }: {
  histograms: Record<string, HistogramItem[]>; totals?: Record<string, number>;
}) {
  const keys = Object.keys(histograms).filter((k) => histograms[k].length > 0);
  if (keys.length === 0) return null;
  return (
    <div className="media-grid">
      {keys.map((k) => (
        <HistogramKey key={k} name={k} items={histograms[k]} total={totals?.[k] ?? histograms[k].length} />
      ))}
    </div>
  );
}
