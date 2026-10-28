import type { RunRange } from "../types";

/** The step ranges a run marked (`run.mark_range`), named under the chart
 *  toolbar: the charts shade them as unlabelled x bands. */
export default function RangeLegend({ ranges, total }: { ranges?: RunRange[] | null; total?: number }) {
  if (!ranges?.length) return null;
  const more = (total ?? ranges.length) - ranges.length;
  return (
    <div data-testid="range-legend" style={{ color: "var(--text-3)", fontSize: 12, marginBottom: 10 }}>
      Shaded ranges: {ranges.map((r) => `${r.name} ${r.start_step}–${r.end_step}`).join(", ")}
      {more > 0 && ` (+${more} more)`}
    </div>
  );
}
