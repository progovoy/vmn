import { useCallback, useRef, useState } from "react";
import { useDismiss } from "../hooks/useDismiss";

function Section({ title, columns, visible, onToggle }: {
  title?: string;
  columns: string[];
  visible: string[];
  onToggle: (col: string) => void;
}) {
  if (columns.length === 0) return null;
  return (
    <div className="col-picker-section">
      {title && <div className="col-picker-title">{title}</div>}
      {columns.map((col) => (
        <label key={col} className="col-picker-item">
          <input
            type="checkbox"
            checked={visible.includes(col)}
            onChange={() => onToggle(col)}
            aria-label={col}
          />
          {col}
        </label>
      ))}
    </div>
  );
}

/** Show/hide leaderboard columns: params (*columns*) and, when given, metric
 *  columns and other columns (tags) in sections of their own — filterable
 *  once there are many. Escape or a click outside closes it. */
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
