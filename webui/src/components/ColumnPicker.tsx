import { useCallback, useRef, useState } from "react";
import { useDismiss } from "../hooks/useDismiss";

/** Toggle every column in *columns* whose current visibility differs from
 *  *want* — as many `onToggle` calls as columns that actually need to flip. */
function applyVisibility(
  columns: string[],
  visibleSet: ReadonlySet<string>,
  onToggle: (col: string) => void,
  want: (col: string) => boolean,
) {
  columns.forEach((col) => {
    if (visibleSet.has(col) !== want(col)) onToggle(col);
  });
}

function Section({ title, columns, visible, onToggle }: {
  title?: string;
  columns: string[];
  visible: string[];
  onToggle: (col: string) => void;
}) {
  if (columns.length === 0) return null;
  const label = title ?? "columns";
  const visibleSet = new Set(visible);
  const allVisible = columns.every((c) => visibleSet.has(c));
  const noneVisible = columns.every((c) => !visibleSet.has(c));
  return (
    <div className="col-picker-section">
      <div className="col-picker-section-head">
        {title && <span className="col-picker-title">{title}</span>}
        <button
          type="button" className="link" disabled={allVisible}
          aria-label={`Show all ${label}`}
          onClick={() => applyVisibility(columns, visibleSet, onToggle, () => true)}
        >
          all
        </button>
        <button
          type="button" className="link" disabled={noneVisible}
          aria-label={`Hide all ${label}`}
          onClick={() => applyVisibility(columns, visibleSet, onToggle, () => false)}
        >
          none
        </button>
      </div>
      {columns.map((col) => (
        <div key={col} className="col-picker-item">
          <label>
            <input
              type="checkbox"
              checked={visibleSet.has(col)}
              onChange={() => onToggle(col)}
              aria-label={col}
            />
            {col}
          </label>
          <button
            type="button" className="link col-picker-only"
            aria-label={`Show only ${col}`}
            onClick={() => applyVisibility(columns, visibleSet, onToggle, (c) => c === col)}
          >
            only
          </button>
        </div>
      ))}
    </div>
  );
}

/** Show/hide leaderboard columns: params (*columns*) and, when given, metric
 *  columns and other columns (tags) in sections of their own — filterable
 *  once there are many, with "all"/"none" and per-row "only" bulk actions
 *  scoped to each section (and to the current filter). Escape or a click
 *  outside closes it. */
export default function ColumnPicker({
  columns, visible, onToggle, metricColumns = [], visibleMetrics = [], onToggleMetric,
  otherColumns = [], visibleOther = [], onToggleOther,
}: {
  columns: string[];
  visible: string[];
  onToggle: (col: string) => void;
  metricColumns?: string[];
  visibleMetrics?: string[];
  onToggleMetric?: (col: string) => void;
  otherColumns?: string[];
  visibleOther?: string[];
  onToggleOther?: (col: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, button);

  if (columns.length + metricColumns.length + otherColumns.length === 0) return null;

  const needle = filter.trim().toLowerCase();
  const match = (cols: string[]) =>
    needle ? cols.filter((c) => c.toLowerCase().includes(needle)) : cols;
  const hasMetrics = metricColumns.length > 0 && onToggleMetric;

  return (
    <div ref={box} style={{ position: "relative", display: "inline-block" }}>
      <button
        ref={button} title="Columns" aria-haspopup="true" aria-expanded={open}
        onClick={() => setOpen((v) => !v)} style={{ padding: "4px 10px" }}
      >
        Columns {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="col-picker">
          <input
            type="text"
            aria-label="Filter columns"
            placeholder="Filter columns…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            autoFocus
          />
          {hasMetrics && (
            <Section
              title="metrics"
              columns={match(metricColumns)}
              visible={visibleMetrics}
              onToggle={onToggleMetric}
            />
          )}
          <Section
            title={hasMetrics ? "params" : undefined}
            columns={match(columns)}
            visible={visible}
            onToggle={onToggle}
          />
          {onToggleOther && (
            <Section title="other" columns={match(otherColumns)} visible={visibleOther} onToggle={onToggleOther} />
          )}
        </div>
      )}
    </div>
  );
}
