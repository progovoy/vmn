import { useState } from "react";

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
 *  columns in a section of their own — filterable once there are many. */
export default function ColumnPicker({
  columns, visible, onToggle, metricColumns = [], visibleMetrics = [], onToggleMetric,
}: {
  columns: string[];
  visible: string[];
  onToggle: (col: string) => void;
  metricColumns?: string[];
  visibleMetrics?: string[];
  onToggleMetric?: (col: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");

  if (columns.length + metricColumns.length === 0) return null;

  const needle = filter.trim().toLowerCase();
  const match = (cols: string[]) =>
    needle ? cols.filter((c) => c.toLowerCase().includes(needle)) : cols;
  const hasMetrics = metricColumns.length > 0 && onToggleMetric;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button title="Columns" onClick={() => setOpen((v) => !v)} style={{ padding: "4px 10px" }}>
        ⋮
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
        </div>
      )}
    </div>
  );
}
