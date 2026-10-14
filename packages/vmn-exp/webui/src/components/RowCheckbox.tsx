/** A board row's or card's selection checkbox; shift-click extends the
 *  selection from the last toggled run. */
export default function RowCheckbox({ verstr, checked, onToggle }: {
  verstr: string; checked: boolean; onToggle: (verstr: string, range: boolean) => void;
}) {
  return (
    <input
      type="checkbox" checked={checked} aria-label={`Select ${verstr}`}
      onChange={() => {}} onClick={(e) => onToggle(verstr, e.shiftKey)}
    />
  );
}
