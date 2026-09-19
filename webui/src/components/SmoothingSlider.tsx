interface Props {
  value: number;
  onChange: (v: number) => void;
}

export default function SmoothingSlider({ value, onChange }: Props) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
      <span style={{ color: "var(--text-3)" }}>smoothing</span>
      <input
        type="range"
        min="0"
        max="0.99"
        step="0.01"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: 80 }}
      />
      <span className="mono" style={{ minWidth: 32 }}>{value}</span>
    </label>
  );
}
