import ToggleChip from "./ToggleChip";

/** Log y as an on/off chip: pressed (and tinted) while the axis is logarithmic. */
export function LogToggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <ToggleChip pressed={value} onChange={onChange}
      title="logarithmic y axis (non-positive values are left out)">
      Log y
    </ToggleChip>
  );
}

export function MetricSearch({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="search"
      placeholder="filter metrics"
      aria-label="filter metrics"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ fontSize: 12, padding: "2px 8px", width: 140 }}
    />
  );
}
