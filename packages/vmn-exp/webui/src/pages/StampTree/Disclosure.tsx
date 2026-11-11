/** Disclosure header shared by the changelog and config sections. */
export function Disclosure({ open, onToggle, label }: {
  open: boolean; onToggle: () => void; label: string;
}) {
  return (
    <button
      onClick={onToggle}
      style={{
        background: "none", border: "none", padding: 0, cursor: "pointer",
        font: "inherit", fontWeight: 600, color: "var(--text-primary)",
        display: "flex", alignItems: "center", gap: 6,
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{open ? "▾" : "▸"}</span>
      {label}
    </button>
  );
}
