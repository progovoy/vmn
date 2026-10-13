interface Props {
  value: number;
  onChange: (v: number) => void;
}

/** The smoothing amount as shown: "off" at zero, else two decimals. */
const smoothingText = (v: number) => (v === 0 ? "off" : v.toFixed(2));

export default function SmoothingSlider({ value, onChange }: Props) {
  const text = smoothingText(value);
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
      <span style={{ color: "var(--text-3)" }}>smoothing</span>
      <input
        type="range"
        min="0"
        max="0.99"
        step="0.01"
        value={value}
        aria-valuetext={text}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: 80 }}
      />
      <span className="mono" style={{ minWidth: 32 }} aria-hidden>{text}</span>
    </label>
  );
}
