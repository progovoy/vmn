import { useState } from "react";

export default function ColumnPicker({ columns, visible, onToggle }: {
  columns: string[];
  visible: string[];
  onToggle: (col: string) => void;
}) {
  const [open, setOpen] = useState(false);

  if (columns.length === 0) return null;

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button title="Columns" onClick={() => setOpen((v) => !v)} style={{ padding: "4px 10px" }}>
        ⋮
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            zIndex: 10,
            background: "var(--panel-2)",
            border: "1px solid var(--line)",
            borderRadius: 8,
            padding: "8px 12px",
            minWidth: 140,
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
          }}
        >
          {columns.map((col) => (
            <label key={col} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 0", cursor: "pointer", fontSize: 13 }}>
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
      )}
    </div>
  );
}
