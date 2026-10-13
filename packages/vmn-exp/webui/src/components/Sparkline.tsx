/** A tiny inline histogram: one bar per bin, scaled to the fullest (plan 23
 *  W1: a job's Spread). Nothing when every bin is empty. */
import "./jobProgress.css";

const BAR_W = 4;
const GAP = 1;

export default function Sparkline({ counts, title, height = 16 }: {
  counts: readonly number[]; title: string; height?: number;
}) {
  const top = Math.max(0, ...counts);
  if (top <= 0) return null;
  const width = counts.length * (BAR_W + GAP) - GAP;
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
      <title>{title}</title>
      {counts.map((c, i) => {
        const h = Math.round((c / top) * height * 100) / 100;
        return <rect key={i} x={i * (BAR_W + GAP)} y={height - h} width={BAR_W} height={h} />;
      })}
    </svg>
  );
}
